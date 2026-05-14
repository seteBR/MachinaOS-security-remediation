"""Plugins for the 'browser' palette group. See ../__init__.py for the package layout.

Self-registration on import:
  - FastAPI lifespan shutdown hook (Wave 12 C4 sub-piece B) — the
    agent-browser daemon needs an explicit close to release file
    locks. Registered through ``services.plugin.shutdown_hooks`` so
    ``main.py`` lifespan teardown reaches us without cross-plugin
    imports.
"""

from services.plugin.shutdown_hooks import register_shutdown_hook

from ._service import shutdown_browser_service

register_shutdown_hook("browser_service", shutdown_browser_service)
