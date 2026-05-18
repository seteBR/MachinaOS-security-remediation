"""Unit tests for :mod:`services.plugin.ws` + :mod:`services.plugin.deps`.

Locks the contract for the two T-residual helpers added in Wave 11.I:

* :func:`services.plugin.ws.ws_response` -- exception-to-envelope wrapper
  with ``NodeUserError`` carve-out.
* :func:`services.plugin.deps.get_auth_service` /
  ``get_database`` / ``get_cache`` -- NOT memoised; re-resolve on
  every call so test container overrides take effect.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from services.plugin.base import NodeUserError
from services.plugin.deps import get_auth_service, get_cache, get_database
from services.plugin.ws import ws_response


# ----------------------------------------------------------------------------
# ws_response
# ----------------------------------------------------------------------------


class TestWsResponse:
    """``@ws_response`` -- opt-in exception-to-envelope decorator."""

    async def test_success_path_passes_through_unchanged(self):
        @ws_response
        async def handler(data, websocket):
            return {"success": True, "result": "ok", "extra": 42}

        out = await handler({}, MagicMock())
        assert out == {"success": True, "result": "ok", "extra": 42}

    async def test_unexpected_exception_returns_error_envelope(self):
        @ws_response
        async def handler(data, websocket):
            raise RuntimeError("server bug")

        out = await handler({}, MagicMock())
        assert out == {"success": False, "error": "server bug"}

    async def test_node_user_error_returns_error_envelope(self):
        @ws_response
        async def handler(data, websocket):
            raise NodeUserError("missing required field")

        out = await handler({}, MagicMock())
        assert out == {"success": False, "error": "missing required field"}

    async def test_decorator_preserves_handler_metadata(self):
        @ws_response
        async def documented_handler(data, websocket):
            """Original docstring."""
            return {"success": True}

        assert documented_handler.__name__ == "documented_handler"
        assert documented_handler.__doc__ == "Original docstring."


# ----------------------------------------------------------------------------
# deps -- get_auth_service / get_database / get_cache
# ----------------------------------------------------------------------------


class TestLazyDependencyHelpers:
    """The lazy DI helpers MUST NOT memoise -- test fixtures rely on
    call-time container resolution to swap singletons mid-test."""

    def test_get_auth_service_returns_container_singleton(self):
        fake_auth = MagicMock(name="auth_service_singleton")
        with patch("core.container.container") as fake_container:
            fake_container.auth_service.return_value = fake_auth
            assert get_auth_service() is fake_auth

    def test_get_database_returns_container_singleton(self):
        fake_db = MagicMock(name="database_singleton")
        with patch("core.container.container") as fake_container:
            fake_container.database.return_value = fake_db
            assert get_database() is fake_db

    def test_get_cache_returns_container_singleton(self):
        fake_cache = MagicMock(name="cache_singleton")
        with patch("core.container.container") as fake_container:
            fake_container.cache.return_value = fake_cache
            assert get_cache() is fake_cache

    def test_get_auth_service_is_not_memoised(self):
        """Two consecutive calls must each re-query the container.

        Test monkeypatching swaps the container's auth-service mid-test.
        A memoised cache would lock in the first instance and the swap
        would be silently ignored.
        """
        first = MagicMock(name="first_auth_service")
        second = MagicMock(name="second_auth_service")
        with patch("core.container.container") as fake_container:
            fake_container.auth_service.side_effect = [first, second]
            assert get_auth_service() is first
            assert get_auth_service() is second
        # Verify the container was queried twice -- not a single cached
        # lookup (which would mean side_effect's second value is unused).
        assert fake_container.auth_service.call_count == 2

    def test_get_database_is_not_memoised(self):
        first = MagicMock(name="first_db")
        second = MagicMock(name="second_db")
        with patch("core.container.container") as fake_container:
            fake_container.database.side_effect = [first, second]
            assert get_database() is first
            assert get_database() is second
        assert fake_container.database.call_count == 2
