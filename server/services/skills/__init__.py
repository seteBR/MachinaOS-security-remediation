"""Skills domain — Wave 13 extraction from ``routers/websocket.py``.

Owns the 13 WebSocket handlers covering built-in + user skills + auto-skill
policy + memory/skill reset. Centralising them here drops ~360 LOC out of
the monolithic ``routers/websocket.py`` and matches the pattern Wave 11.I
established for plugin-scoped handlers (telegram / whatsapp / android /
google / twitter / stripe).

Side-effect import: registers all 13 handlers into the central
``services.ws_handler_registry`` via :func:`register_ws_handlers`. The
WS router resolves dispatch via that registry, so importing this module
is the only wiring step.
"""

from __future__ import annotations

from services.ws_handler_registry import register_ws_handlers as _register_ws_handlers

from .handlers import WS_HANDLERS as _SKILL_WS_HANDLERS

_register_ws_handlers(_SKILL_WS_HANDLERS)

__all__ = ["handlers"]
