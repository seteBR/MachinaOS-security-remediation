"""Anthropic Claude Code CLI provider.

Reference implementation for the `AICliProvider` Protocol. Full feature
set: sessions, resume, budget, turns, allowed_tools, permission_mode,
MCP lockfile, cost-in-JSON.

Subprocess: ``claude -p <prompt> --output-format stream-json --verbose
--include-partial-messages --include-hook-events --ide
[--session-id|--resume <UUID>] --model ... --max-turns ...
--max-budget-usd ... --allowedTools ... --permission-mode ...
--append-system-prompt ... [--effort ...] [--fallback-model ...]
[--add-dir ...] [--disallowedTools ...] [--agent ...]``

Binary + auth: shared with the auth surface via
``services.claude_oauth.claude_binary_path()`` — single project-local
install at ``<repo>/data/claude-machina/npm/`` and ``CLAUDE_CONFIG_DIR``
set on the spawn env so the agent picks up the same credentials the
Login button wrote.

Final event: ``type == "result"`` carries ``total_cost_usd``,
``duration_ms``, ``num_turns``, ``session_id``, and the assistant's
``result`` string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import get_logger

from services.claude_oauth import claude_binary_path
from services.cli_agent.config import get_provider_config
from services.cli_agent.protocol import CanonicalUsage
from services.cli_agent.types import ClaudeTaskSpec

logger = get_logger(__name__)

NAME = "claude"


class AnthropicClaudeProvider:
    """`AICliProvider` for Anthropic's Claude Code CLI."""

    def __init__(self) -> None:
        cfg = get_provider_config(NAME)
        if cfg is None:
            raise RuntimeError(
                f"Provider config missing for {NAME!r}. Check ai_cli_providers.json."
            )
        self.name = NAME
        self.package_name = cfg.package_name
        self.binary_name = cfg.binary_name
        self.ide_lock_env_var = cfg.ide_lock_env_var
        self.ide_lockfile_dir = cfg.ide_lockfile_dir
        self._defaults = cfg.defaults
        self._supports = cfg.supports
        self._login_argv = cfg.login_argv
        self._auth_status_argv = cfg.auth_status_argv

    # ---- spawn surface ---------------------------------------------------

    def binary_path(self) -> Path:
        """Resolve the project-local `claude` binary.

        Delegates to ``services.claude_oauth.claude_binary_path`` — same
        path used by the credentials Login button. Lazy-installs into
        ``<repo>/data/claude-machina/npm/`` on first miss. Raises
        ``FileNotFoundError`` if ``npm`` isn't on PATH.
        """
        return Path(claude_binary_path())

    def headless_argv(
        self,
        task: Any,  # ClaudeTaskSpec
        *,
        defaults: Dict[str, Any],
        mcp_endpoint_url: Optional[str] = None,
        mcp_bearer_token: Optional[str] = None,
        connected_tool_names: Optional[List[str]] = None,
    ) -> List[str]:
        """Build the full argv (binary + flags) for one task.

        ``mcp_endpoint_url`` + ``mcp_bearer_token`` (if both set) are
        emitted as a ``--mcp-config <json>`` block so the spawned
        ``claude -p`` registers MachinaOs's MCP server. The ``--ide`` /
        lockfile path is for interactive IDE-host scenarios; in headless
        mode the documented mechanism is ``--mcp-config`` (see
        https://code.claude.com/docs/en/mcp)."""
        if not isinstance(task, ClaudeTaskSpec):
            raise TypeError(
                "AnthropicClaudeProvider.headless_argv requires ClaudeTaskSpec, "
                f"got {type(task).__name__}"
            )

        argv: List[str] = [str(self.binary_path())]

        argv += [
            "-p", task.prompt,
            "--output-format", "stream-json",
            "--verbose",  # required by Claude CLI when using stream-json with --print
            "--include-partial-messages",
            "--include-hook-events",  # surface SessionStart / hooks into stream-json
        ]

        # MCP server registration — headless path. The shape mirrors
        # the Claude Code MCP doc's ``mcp.json`` example and the
        # ``claude mcp add --transport http <name> <url> --header
        # "Authorization: Bearer ..."`` invocation.
        if mcp_endpoint_url and mcp_bearer_token:
            # `alwaysLoad: true` opts this server out of MCP tool-search
            # deferral so all `mcp__machinaos__*` tools enter context at
            # session start instead of waiting for a `ToolSearch` call
            # that the agent often doesn't make
            # (https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search).
            # Startup blocks <=5s waiting for the FastMCP connection;
            # acceptable since our server is already up before spawn.
            mcp_payload = json.dumps({
                "mcpServers": {
                    "machinaos": {
                        "type": "http",
                        "url": mcp_endpoint_url,
                        "headers": {
                            "Authorization": f"Bearer {mcp_bearer_token}",
                        },
                        "alwaysLoad": True,
                    }
                }
            })
            argv += ["--mcp-config", mcp_payload, "--strict-mcp-config"]

        # Model
        model = (
            task.model
            or defaults.get("default_model")
            or self._defaults.get("default_model", "claude-sonnet-4-6")
        )
        argv += ["--model", model]

        # Session / resume — `resume_session_id` wins if both are set,
        # since "resume" implies the user has a prior session.
        if task.resume_session_id:
            argv += ["--resume", task.resume_session_id]
        elif task.session_id:
            argv += ["--session-id", task.session_id]

        # Max turns
        max_turns = (
            task.max_turns
            if task.max_turns is not None
            else int(defaults.get(
                "default_max_turns",
                self._defaults.get("default_max_turns", 10),
            ))
        )
        argv += ["--max-turns", str(max_turns)]

        # Budget (USD)
        max_budget = (
            task.max_budget_usd
            if task.max_budget_usd is not None
            else float(defaults.get(
                "default_max_budget_usd",
                self._defaults.get("default_max_budget_usd", 5.0),
            ))
        )
        if max_budget > 0:
            argv += ["--max-budget-usd", str(max_budget)]

        # Allowed tools — built-in defaults plus every workflow tool we
        # exposed via the per-batch FastMCP bridge. Without the
        # `mcp__machinaos__<name>` entries here, claude sees the tools
        # in `tools/list` but is denied permission when it tries to
        # invoke them ("I don't have permission to run a web search…")
        # because `--permission-mode acceptEdits` only auto-permits
        # Edit; everything else falls through to the allowlist.
        # Default fallback includes:
        #   - Read,Edit,Bash,Glob,Grep,Write — filesystem + shell escape hatches
        #   - Skill — invoke materialised `.claude/skills/<name>/SKILL.md`
        #   - WebSearch,WebFetch — escape hatches when no MCP tool matches
        # `ToolSearch` is intentionally NOT here: it's permission-free per
        # https://code.claude.com/docs/en/tools-reference#built-in-tools.
        allowed = task.allowed_tools or defaults.get(
            "default_allowed_tools",
            self._defaults.get(
                "default_allowed_tools",
                "Read,Edit,Bash,Glob,Grep,Write,Skill,WebSearch,WebFetch",
            ),
        )
        allowed_list: List[str] = (
            [t.strip() for t in allowed.split(",") if t.strip()]
            if allowed else []
        )
        if connected_tool_names:
            allowed_list += [
                f"mcp__machinaos__{name}" for name in connected_tool_names
            ]
        # Always permit MachinaOs's built-in MCP tools so the agent can
        # discover skills + read workspace files without prompting.
        allowed_list += [
            "mcp__machinaos__getWorkspaceFiles",
            "mcp__machinaos__listSkills",
            "mcp__machinaos__getSkill",
            "mcp__machinaos__getCredential",
            "mcp__machinaos__broadcastLog",
        ]
        if allowed_list:
            argv += ["--allowedTools", ",".join(allowed_list)]

        # Permission mode (default acceptEdits)
        perm = task.permission_mode or defaults.get(
            "default_permission_mode",
            self._defaults.get("default_permission_mode", "acceptEdits"),
        )
        if perm:
            argv += ["--permission-mode", perm]

        # System prompt — appended to Claude Code's built-in system prompt
        if task.system_prompt:
            argv += ["--append-system-prompt", task.system_prompt]

        # Connected-tools steering directive — ensures the agent prefers
        # wired MCP tools over built-in escape hatches (WebSearch,
        # WebFetch, Bash) when their purpose matches the user's request.
        # Mirrors Cursor's per-request rule prepend pattern
        # (https://cursor.com/docs/rules). Multiple `--append-system-prompt`
        # flags concatenate per the CLI reference.
        if connected_tool_names:
            tool_list = ", ".join(
                f"mcp__machinaos__{name}" for name in connected_tool_names
            )
            directive = (
                f"Workflow tools wired to this agent: {tool_list}. "
                "Prefer them over built-in equivalents (WebSearch, "
                "WebFetch, Bash) when the user's request matches their "
                "purpose."
            )
            argv += ["--append-system-prompt", directive]

        # Optional per-task overrides (documented at code.claude.com/docs/en/cli-reference)
        if task.effort:
            argv += ["--effort", task.effort]
        if task.fallback_model:
            argv += ["--fallback-model", task.fallback_model]
        for path in task.add_dir:
            argv += ["--add-dir", path]
        if task.disallowed_tools:
            argv += ["--disallowedTools", task.disallowed_tools]
        if task.agent:
            argv += ["--agent", task.agent]

        return argv

    # ---- native auth -----------------------------------------------------

    def login_argv(self) -> List[str]:
        return list(self._login_argv) or ["claude", "login"]

    def auth_status_argv(self) -> Optional[List[str]]:
        return list(self._auth_status_argv) if self._auth_status_argv else None

    def detect_auth_error(self, stderr: str, exit_code: int) -> bool:
        """True if stderr/exit_code indicate the user isn't logged in."""
        if not stderr and exit_code == 0:
            return False
        markers = (
            "Please run 'claude login'",
            "Please run `claude login`",
            "Not authenticated",
            "Authentication required",
            "401 Unauthorized",
            "Invalid API key",
        )
        return any(m in stderr for m in markers)

    # ---- streaming output parsing ---------------------------------------

    def parse_event(self, line: str) -> Optional[Dict[str, Any]]:
        line = line.strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def is_final_event(self, event: Dict[str, Any]) -> bool:
        return event.get("type") == "result"

    def event_to_session_result(
        self,
        events: List[Dict[str, Any]],
        stderr: str,
        exit_code: int,
    ) -> Dict[str, Any]:
        """Reconstruct shared result fields from the event stream."""
        final = next(
            (e for e in reversed(events) if e.get("type") == "result"),
            None,
        )

        # Session ID can come from `system.init` or `result`
        session_id: Optional[str] = None
        for evt in events:
            sid = evt.get("session_id")
            if sid:
                session_id = sid
                break

        tool_calls = sum(
            1 for evt in events
            if evt.get("type") == "tool_use"
            or (evt.get("type") == "assistant" and self._has_tool_use(evt))
        )

        provider_data: Dict[str, Any] = {}
        for evt in events:
            if evt.get("type") == "assistant":
                msg = evt.get("message") or {}
                rd = msg.get("reasoning_details") or msg.get("thinking")
                if rd is not None:
                    provider_data.setdefault("reasoning_details", rd)
                    break

        success = exit_code == 0 and final is not None
        error: Optional[str] = None
        if exit_code != 0:
            error = stderr.strip()[-2000:] or f"claude exited with code {exit_code}"
        elif final is None:
            error = "no result event received"

        response = ""
        cost: Optional[float] = None
        duration_ms: Optional[int] = None
        num_turns: Optional[int] = None
        if final:
            response = str(final.get("result") or "")
            cost = final.get("total_cost_usd")
            duration_ms = final.get("duration_ms")
            num_turns = final.get("num_turns")
            if final.get("subtype") == "error":
                success = False
                error = error or response or "result event reports error"

        cu = self.canonical_usage(events)

        return {
            "session_id": session_id,
            "response": response,
            "cost_usd": cost,
            "duration_ms": duration_ms,
            "num_turns": num_turns,
            "tool_calls": tool_calls,
            "canonical_usage": cu,
            "provider_data": provider_data,
            "success": success,
            "error": error,
        }

    def canonical_usage(self, events: List[Dict[str, Any]]) -> CanonicalUsage:
        """Pull token counts from the `result` event's `usage` block.

        Anthropic shape:
          {
            "input_tokens": int,
            "output_tokens": int,
            "cache_creation_input_tokens": int,
            "cache_read_input_tokens": int,
          }
        """
        final = next(
            (e for e in reversed(events) if e.get("type") == "result"),
            None,
        )
        if not final:
            return CanonicalUsage()

        usage = final.get("usage") or {}
        request_count = (
            int(final.get("num_turns") or 0)
            or sum(1 for e in events if e.get("type") == "assistant")
        )
        return CanonicalUsage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cache_read=int(usage.get("cache_read_input_tokens", 0)),
            cache_write=int(usage.get("cache_creation_input_tokens", 0)),
            reasoning_tokens=0,  # Claude doesn't expose this separately
            request_count=request_count,
        )

    # ---- feature gating --------------------------------------------------

    def supports(self, feature: str) -> bool:
        return feature in self._supports

    # ---- internals -------------------------------------------------------

    @staticmethod
    def _has_tool_use(event: Dict[str, Any]) -> bool:
        msg = event.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            return any(
                isinstance(blk, dict) and blk.get("type") == "tool_use"
                for blk in content
            )
        return False
