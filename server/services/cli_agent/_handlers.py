"""Per-provider WebSocket handlers for CLI-managed OAuth.

Self-registered into ``services.ws_handler_registry`` from
``services/cli_agent/__init__.py``. Naming convention matches Twitter /
Google / Stripe — each provider gets its own message type
(``claude_code_login`` / ``claude_code_logout`` / ``codex_cli_login`` /
``codex_cli_logout``); the frontend dispatches with an empty payload.

Claude flow uses the documented CLI subcommands from
https://code.claude.com/docs/en/cli-reference (``claude auth login`` /
``status`` / ``logout``). Every subprocess invocation goes through
``services.events.cli.run_cli_command`` (Stripe precedent — see
``nodes/stripe/_handlers.py``); the CLI owns its own credentials file
and we never touch it.

Login lifecycle:

1. ``handle_claude_code_login`` schedules ``run_claude_login`` as an
   ``asyncio.create_task`` (mirrors Stripe's ``stripe login --complete``)
   and returns immediately. The CLI opens the user's browser; up to
   10 minutes are allowed for the flow to complete.
2. When the task resolves, ``_finalize_claude_login`` reads
   ``claude auth status``, stores the synthetic ``"cli-managed"`` marker
   along with the user's ``email``/``orgName`` via
   ``auth_service.store_oauth_tokens()``, and fires
   ``broadcast_credential_event("credential.oauth.connected", ...)`` —
   the frontend's ``WebSocketContext`` re-fetches the catalogue.

Logout runs ``claude auth logout`` (CLI clears its own credentials),
drops the catalogue marker, and broadcasts ``.disconnected``.

Codex login is not yet wired (no ``codex_oauth.py``); the handler returns
a graceful error pointing the user at the manual flow.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import WebSocket

from core.logging import get_logger

logger = get_logger(__name__)


# Synthetic marker stored in `auth_service` after a successful CLI login,
# matching `nodes/stripe/_handlers.py:_MARKER_TOKEN`. Lets the catalogue's
# generic `stored` check flip without per-provider code in the catalogue
# handler.
_MARKER_TOKEN = "cli-managed"


# ---------------------------------------------------------------------------
# Marker-token + credential-event broadcast (Stripe pattern)
# ---------------------------------------------------------------------------

async def _mark_logged_in(
    catalogue_key: str,
    *,
    email: Optional[str] = None,
    name: Optional[str] = None,
) -> None:
    from core.container import container
    await container.auth_service().store_oauth_tokens(
        provider=catalogue_key,
        access_token=_MARKER_TOKEN,
        refresh_token=_MARKER_TOKEN,
        email=email,
        name=name,
    )


async def _mark_logged_out(catalogue_key: str) -> None:
    from core.container import container
    await container.auth_service().remove_oauth_tokens(catalogue_key)


async def _broadcast_credential_event(event_type: str, provider: str) -> None:
    """Fire a CloudEvents-shaped catalogue-invalidation. Frontend listens
    via ``WebSocketContext`` and re-fetches the catalogue."""
    from services.status_broadcaster import get_status_broadcaster
    await get_status_broadcaster().broadcast_credential_event(
        event_type, provider=provider,
    )


# ---------------------------------------------------------------------------
# Claude — `claude auth login` / `auth status` / `auth logout`
# ---------------------------------------------------------------------------

async def _finalize_claude_login() -> None:
    """Run ``claude auth login`` to completion, then store user info +
    broadcast on success."""
    from nodes.agent.claude_code_agent._oauth import claude_auth_status_info, run_claude_login

    try:
        envelope = await run_claude_login()
        if not envelope.get("success"):
            logger.warning(
                "[claude_code_login] CLI exited unsuccessfully: %s",
                envelope.get("error") or envelope.get("stderr"),
            )
            return

        info = await claude_auth_status_info()
        if not info.get("loggedIn"):
            logger.warning(
                "[claude_code_login] CLI exited cleanly but auth status "
                "reports not logged in: %s", info,
            )
            return

        email = info.get("email")
        org_name = info.get("orgName")
        await _mark_logged_in("claude_code", email=email, name=org_name)
        await _broadcast_credential_event(
            "credential.oauth.connected", provider="claude_code",
        )
        logger.info(
            "[claude_code_login] connected as %s (%s · %s)",
            email or "unknown",
            org_name or "unknown org",
            info.get("subscriptionType") or "unknown plan",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("[claude_code_login] finalize failed: %s", exc)


async def handle_claude_code_login(
    data: Dict[str, Any],  # noqa: ARG001 — frontend sends {}
    websocket: WebSocket,  # noqa: ARG001 — registry signature
) -> Dict[str, Any]:
    """Spawn ``claude auth login`` in the background; let the CLI open
    the user's browser. Idempotent re-click syncs the marker without
    re-running the flow."""
    from nodes.agent.claude_code_agent._oauth import claude_auth_status_info

    info = await claude_auth_status_info()
    if info.get("loggedIn"):
        try:
            await _mark_logged_in(
                "claude_code",
                email=info.get("email"),
                name=info.get("orgName"),
            )
            await _broadcast_credential_event(
                "credential.oauth.connected", provider="claude_code",
            )
        except Exception as exc:
            logger.warning("[claude_code_login] mark/broadcast failed: %s", exc)
        return {
            "success": True,
            "already_logged_in": True,
            "email": info.get("email"),
            "org_name": info.get("orgName"),
            "subscription_type": info.get("subscriptionType"),
            "message": "Already authenticated; refreshed status.",
        }

    asyncio.create_task(_finalize_claude_login(), name="claude_code_login")
    return {
        "success": True,
        "message": "Claude is opening your browser to authenticate.",
    }


async def handle_claude_code_logout(
    data: Dict[str, Any],  # noqa: ARG001
    websocket: WebSocket,  # noqa: ARG001
) -> Dict[str, Any]:
    """Run ``claude auth logout`` (CLI clears its own credentials), drop
    the catalogue marker, broadcast ``.disconnected``."""
    from nodes.agent.claude_code_agent._oauth import claude_auth_logout

    try:
        await claude_auth_logout()
        await _mark_logged_out("claude_code")
        await _broadcast_credential_event(
            "credential.oauth.disconnected", provider="claude_code",
        )
    except Exception as exc:
        logger.warning("[claude_code_logout] failed: %s", exc)
        return {"success": False, "error": str(exc)}
    return {"success": True}


# ---------------------------------------------------------------------------
# Codex — login flow not yet wired; logout works for marker cleanup
# ---------------------------------------------------------------------------

async def handle_codex_cli_login(
    data: Dict[str, Any],  # noqa: ARG001
    websocket: WebSocket,  # noqa: ARG001
) -> Dict[str, Any]:
    return {
        "success": False,
        "error": (
            "Codex login is not yet wired in MachinaOs. "
            "Install with `npm install -g @openai/codex` and run "
            "`codex login` in your terminal — then click Login again "
            "to mark connected."
        ),
    }


async def handle_codex_cli_logout(
    data: Dict[str, Any],  # noqa: ARG001
    websocket: WebSocket,  # noqa: ARG001
) -> Dict[str, Any]:
    try:
        await _mark_logged_out("codex_cli")
        await _broadcast_credential_event(
            "credential.oauth.disconnected", provider="codex_cli",
        )
    except Exception as exc:
        logger.warning("[codex_cli_logout] failed: %s", exc)
        return {"success": False, "error": str(exc)}
    return {"success": True}


# ---------------------------------------------------------------------------
# Registry payload — `services/cli_agent/__init__.py` registers these
# into `services.ws_handler_registry` on package import.
# ---------------------------------------------------------------------------

WSHandler = Callable[[Dict[str, Any], WebSocket], Awaitable[Dict[str, Any]]]

WS_HANDLERS: Dict[str, WSHandler] = {
    "claude_code_login": handle_claude_code_login,
    "claude_code_logout": handle_claude_code_logout,
    "codex_cli_login": handle_codex_cli_login,
    "codex_cli_logout": handle_codex_cli_logout,
}
