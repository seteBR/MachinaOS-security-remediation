"""Claude OAuth — project-local install + the documented `claude auth` subcommands.

The Claude Code CLI lives at ``<machina_root>/claude/npm/`` (on-demand
``npm install`` on first use, mirroring the WhatsApp project-local layout).
``CLAUDE_CONFIG_DIR`` points at ``<machina_root>/claude/`` so the CLI
manages its own credentials inside the project tree, isolated from the
user's own ``~/.claude/`` session. Path resolution is centralised in
:mod:`core.paths` — this module just re-exports the constants for
back-compat with consumers that still ``import MACHINA_CLAUDE_DIR``
directly.

Every subprocess call goes through ``services.events.cli.run_cli_command``
— the canonical one-shot CLI helper used by Stripe / future plugins. Auth
surface follows https://code.claude.com/docs/en/cli-reference verbatim:

- ``claude auth login``  — opens the browser, writes credentials.
- ``claude auth status`` — prints JSON; exits 0 when logged in / 1 otherwise.
- ``claude auth logout`` — log out (CLI clears its own credentials).

The CLI owns its own credentials file; we never read or write it.
``login`` is a long-running one-shot (waits for the browser flow to
complete) so callers schedule it as ``asyncio.create_task`` — same shape
Stripe uses for ``stripe login --complete``.

This module lives alongside the ``claude_code_agent`` plugin so all
claude-specific code stays in one folder per the canonical plugin
pattern. Consumers in ``services/cli_agent/`` (the generic framework)
and the plugin's other modules (``_provider``, ``_pool``, ``_skills``)
import ``MACHINA_CLAUDE_DIR`` from here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict

from core.logging import get_logger
from core.paths import claude_config_dir, claude_npm_dir
from services.events.cli import run_cli_command

logger = get_logger(__name__)

# Single source of truth for path resolution lives in ``core.paths``;
# we re-export as module constants so existing imports
# (``from ._oauth import MACHINA_CLAUDE_DIR``) keep working without a
# function-call indirection at every call site. Call ``machina_root``
# / ``claude_config_dir`` at module load — Settings is already
# initialised by the time this module is first imported (node registry
# discovery runs after the FastAPI app is built).
MACHINA_CLAUDE_DIR = claude_config_dir()
MACHINA_NPM_DIR = claude_npm_dir()

# Generous timeout for browser-flow login; Stripe uses the same window.
LOGIN_TIMEOUT_SECONDS = 600.0
# One-shot status / logout return immediately.
ONESHOT_TIMEOUT_SECONDS = 30.0


def claude_binary_path() -> str:
    """Return path to the project-local claude CLI, installing on miss.

    Single source of truth shared by the auth handler (``_handlers.py``)
    AND the agent spawn (``_provider.py``) so both surfaces use the
    same binary + ``CLAUDE_CONFIG_DIR``-isolated credentials.
    """
    if sys.platform == "win32":
        bin_path = MACHINA_NPM_DIR / "node_modules" / ".bin" / "claude.cmd"
    else:
        bin_path = MACHINA_NPM_DIR / "node_modules" / ".bin" / "claude"

    if bin_path.exists():
        return str(bin_path)

    logger.info("Installing Claude Code CLI in project-local environment...")
    MACHINA_NPM_DIR.mkdir(parents=True, exist_ok=True)

    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        raise FileNotFoundError("npm not found on PATH")

    result = subprocess.run(
        [npm_cmd, "install", "@anthropic-ai/claude-code", "--prefix", str(MACHINA_NPM_DIR)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"npm install failed: {result.stderr}")
        raise RuntimeError(f"Failed to install claude-code: {result.stderr}")

    if not bin_path.exists():
        raise FileNotFoundError(f"Claude CLI not found at {bin_path} after install")

    logger.info(f"Claude Code CLI installed at: {bin_path}")
    return str(bin_path)


def _claude_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(MACHINA_CLAUDE_DIR)
    return env


async def _run_auth(subcommand: str, *, timeout: float) -> Dict[str, Any]:
    """Run ``claude auth <subcommand>`` via the canonical helper. Returns
    the ``run_cli_command`` envelope (``{success, result, stdout, stderr,
    error}``)."""
    try:
        binary = claude_binary_path()
    except (FileNotFoundError, RuntimeError) as e:
        return {"success": False, "error": str(e), "stdout": "", "stderr": ""}

    MACHINA_CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    envelope = await run_cli_command(
        binary=binary,
        argv=["auth", subcommand],
        timeout=timeout,
        env=_claude_env(),
    )
    logger.info(
        "[claude auth %s] success=%s stdout=%r stderr=%r",
        subcommand,
        envelope.get("success"),
        (envelope.get("stdout") or "")[:512],
        (envelope.get("stderr") or "")[:512],
    )
    return envelope


async def claude_auth_status_info() -> Dict[str, Any]:
    """Return parsed JSON from ``claude auth status``. Always includes
    ``loggedIn: bool``; populates ``email``/``orgName``/``subscriptionType``
    when logged in."""
    envelope = await _run_auth("status", timeout=ONESHOT_TIMEOUT_SECONDS)
    parsed = envelope.get("result")
    if isinstance(parsed, dict):
        parsed.setdefault("loggedIn", bool(envelope.get("success")))
        return parsed

    # Status returns exit 1 when not logged in; the JSON still parses but
    # run_cli_command treats non-zero exits as failure and skips parsing.
    # Fall back to parsing stdout directly so we still surface the body.
    stdout = envelope.get("stdout") or ""
    if stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                data.setdefault("loggedIn", False)
                return data
        except json.JSONDecodeError:
            pass
    return {"loggedIn": bool(envelope.get("success"))}


async def claude_auth_status() -> bool:
    """True iff ``claude auth status`` reports loggedIn=True."""
    info = await claude_auth_status_info()
    return bool(info.get("loggedIn"))


async def run_claude_login() -> Dict[str, Any]:
    """Run ``claude auth login`` to completion. The CLI opens the user's
    browser, runs its own callback server, and exits when the flow ends.

    Long-running: callers should schedule this via ``asyncio.create_task``
    (Stripe ``stripe login --complete`` precedent). Returns the envelope
    from ``run_cli_command``."""
    return await _run_auth("login", timeout=LOGIN_TIMEOUT_SECONDS)


async def claude_auth_logout() -> bool:
    """Run ``claude auth logout``. True on exit 0."""
    envelope = await _run_auth("logout", timeout=ONESHOT_TIMEOUT_SECONDS)
    return bool(envelope.get("success"))
