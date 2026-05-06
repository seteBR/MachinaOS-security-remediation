"""Twitter / X OAuth callback router — factory-built (Wave 11.I, S).

The single ``GET /api/twitter/callback`` route comes from
:func:`services.events.oauth_lifecycle.make_oauth_callback_router`.
Pre-S the file hand-rolled the callback + status + logout REST routes
(~370 LOC). Status + logout were duplicates of the WS handlers in
``_handlers.py`` and have been retired -- the WS path is canonical.
"""

from __future__ import annotations

from typing import Any, Dict

from services.events.oauth_lifecycle import make_oauth_callback_router

from ._handlers import _twitter_oauth_factory


def _user_info_to_email(info: Dict[str, Any]) -> str:
    """X has no email field -- use ``@username`` as the identifier."""
    return f"@{info.get('username', 'unknown')}"


router = make_oauth_callback_router(
    provider="twitter",
    oauth_factory=_twitter_oauth_factory,
    user_info_to_email=_user_info_to_email,
    color_hex="#00ba7c",  # X brand green for the success page
)
