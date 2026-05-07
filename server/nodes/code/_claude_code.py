"""Legacy single-task Claude Code shim.

Kept for back-compat with any caller that still imports
`get_claude_code_service()`. New code should call
`services.cli_agent.AICliService.run_batch("claude", ...)` directly via
the `claude_code_agent` plugin.

This module:
  - Builds a single ``ClaudeTaskSpec`` from kwargs
  - Calls ``AICliService.run_batch("claude", ...)``
  - Adapts the ``BatchResult`` back into the dict shape the legacy
    callers expected

Eventually deletable once all imports point at ``cli_agent.service``.
The hardcoded 300s `wait_for` is gone — ``timeout_seconds`` is now per
task and configurable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import Settings
from core.logging import get_logger

from services.cli_agent import ClaudeTaskSpec
from services.cli_agent.service import get_ai_cli_service
from services.plugin.singleton import ServiceSingleton

logger = get_logger(__name__)


class ClaudeCodeService(ServiceSingleton):
    """Thin shim that adapts to the new AICliService."""

    def __init__(self) -> None:
        self._session_map: Dict[str, str] = {}  # node_id -> session_id

    async def execute(
        self,
        prompt: str,
        node_id: str = "",
        model: str = "claude-sonnet-4-6",
        cwd: Optional[str] = None,
        allowed_tools: str = "Read,Edit,Bash,Glob,Grep,Write",
        max_turns: int = 10,
        max_budget_usd: float = 5.0,
        system_prompt: Optional[str] = None,
        timeout_seconds: int = 600,
    ) -> Dict[str, Any]:
        """Run a single Claude Code task. Returns legacy dict shape."""
        if not cwd:
            cwd = os.path.join(Settings().workspace_base_resolved, "default")
            os.makedirs(cwd, exist_ok=True)

        # Resume the prior session for this node if we have one
        resume_session_id = self._session_map.get(node_id) if node_id else None

        task = ClaudeTaskSpec(
            task_id=f"legacy_{node_id}" if node_id else "legacy",
            prompt=prompt,
            model=model,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            allowed_tools=allowed_tools,
            system_prompt=system_prompt,
            timeout_seconds=timeout_seconds,
            resume_session_id=resume_session_id,
        )

        svc = get_ai_cli_service()
        workspace_dir = Path(cwd)
        repo_root = self._find_git_repo(workspace_dir)

        result = await svc.run_batch(
            "claude",
            tasks=[task],
            node_id=node_id or "legacy_node",
            workflow_id="legacy_workflow",
            workspace_dir=workspace_dir,
            broadcaster=None,
            repo_root=repo_root,
        )

        if not result.tasks:
            raise RuntimeError("AICliService returned empty batch")

        sr = result.tasks[0]
        if not sr.success:
            raise RuntimeError(sr.error or "claude_code_service: task failed")

        # Persist session_id for future resume
        if sr.session_id and node_id:
            self._session_map[node_id] = sr.session_id

        return {
            "result": sr.response,
            "session_id": sr.session_id or "",
            "total_cost_usd": sr.cost_usd,
            "duration_ms": sr.duration_ms,
            "num_turns": sr.num_turns,
            "usage": {
                "input_tokens": sr.canonical_usage.input_tokens,
                "output_tokens": sr.canonical_usage.output_tokens,
                "cache_creation_input_tokens": sr.canonical_usage.cache_write,
                "cache_read_input_tokens": sr.canonical_usage.cache_read,
            },
        }

    def get_session_id(self, node_id: str) -> Optional[str]:
        return self._session_map.get(node_id)

    def clear_session(self, node_id: str) -> None:
        self._session_map.pop(node_id, None)

    @staticmethod
    def _find_git_repo(start: Path) -> Optional[Path]:
        """Walk up from `start` looking for a `.git` directory."""
        cur = start.resolve()
        for _ in range(8):
            if (cur / ".git").exists():
                return cur
            if cur.parent == cur:
                return None
            cur = cur.parent
        return None


def get_claude_code_service() -> ClaudeCodeService:
    """Module-level accessor preserved for legacy callers; delegates to
    the :class:`ServiceSingleton` mixin's ``instance()`` classmethod."""
    return ClaudeCodeService.instance()
