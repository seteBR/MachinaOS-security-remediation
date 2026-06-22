"""chatTrigger producer dispatch invariant.

Locks the contract: ``nodes.trigger.chat_trigger._events.dispatch_chat_message_received``
routes through the canary CloudEvents path
(:func:`services.events.dispatch.emit`). In single-process deployments
where the event framework is disabled, it also dispatches to
``event_waiter`` so the legacy in-process listener can spawn workflow
runs.

Same regex-introspection invariant style as
``tests/test_credential_broadcasts.py`` — source-level assertions catch
the wire contract drifting without paying the cost of standing up
Temporal in CI.
"""

from __future__ import annotations

import inspect
import re
import sys
import types
from typing import Any, List
from unittest.mock import MagicMock

import pytest

# Stub `machina` namespace.
if "machina" not in sys.modules:
    _machina = types.ModuleType("cli")
    _machina.__path__ = []
    sys.modules["cli"] = _machina
    _machina_tcp = types.ModuleType("cli.tcp")
    _machina_tcp.probe_tcp_port = MagicMock(return_value=False)
    sys.modules["cli.tcp"] = _machina_tcp


_EVENT_WAITER_DISPATCH_PATTERN = re.compile(r"event_waiter\.dispatch\s*\(")
_EVENTS_EMIT_PATTERN = re.compile(r"\bemit\s*\(")


class TestChatTriggerProducerCanaryEmit:
    """Producer wrapper emits via the canary path with a legacy fallback."""

    def test_dispatcher_is_async(self):
        from nodes.trigger.chat_trigger._events import dispatch_chat_message_received

        assert inspect.iscoroutinefunction(dispatch_chat_message_received), (
            "dispatch_chat_message_received must be async — it awaits " "services.events.dispatch.emit."
        )

    def test_dispatcher_uses_canary_path_and_legacy_fallback(self):
        from nodes.trigger.chat_trigger import _events

        src = inspect.getsource(_events.dispatch_chat_message_received)

        assert _EVENTS_EMIT_PATTERN.search(src), (
            "dispatch_chat_message_received must call "
            "services.events.dispatch.emit(envelope, ...) — the canary "
            "CloudEvents path Signals running TriggerListenerWorkflow "
            "consumers AND broadcasts to FE on the chat_message_received "
            "wire key."
        )
        assert "event_waiter.dispatch_async" in src
        assert not _EVENT_WAITER_DISPATCH_PATTERN.search(src), (
            "dispatch_chat_message_received should use async fallback "
            "dispatch, not sync event_waiter.dispatch inside the request "
            "handler."
        )

    @pytest.mark.asyncio
    async def test_runtime_emits_canary_envelope(self, monkeypatch):
        """Invoking the dispatcher calls dispatch.emit with the right
        envelope."""
        from nodes.trigger.chat_trigger import _events
        from services import event_waiter
        from services.events import dispatch as dispatch_mod

        emit_calls: List[Any] = []
        legacy_calls: List[Any] = []

        async def fake_emit(event, **kwargs):
            emit_calls.append({"event": event, **kwargs})
            return event

        async def fake_dispatch_async(event_type, payload):
            legacy_calls.append((event_type, payload))
            return 1

        monkeypatch.setattr(dispatch_mod, "emit", fake_emit)
        monkeypatch.setattr(event_waiter, "dispatch_async", fake_dispatch_async)
        monkeypatch.setattr(_events, "_event_framework_enabled", lambda: False)

        result = await _events.dispatch_chat_message_received(
            {
                "message": "hello",
                "session_id": "sess-1",
                "timestamp": "2026-05-14T00:00:00",
            }
        )

        # No return value — canary-only emit doesn't carry a waiter count.
        assert result is None

        assert len(emit_calls) == 1
        event = emit_calls[0]["event"]
        assert event.type == "com.machinaos.chat.message.received"
        assert event.subject == "sess-1"
        assert emit_calls[0]["wire_routing_key"] == "chat_message_received"
        assert legacy_calls == [
            (
                "chat_message_received",
                {
                    "message": "hello",
                    "session_id": "sess-1",
                    "timestamp": "2026-05-14T00:00:00",
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_runtime_skips_legacy_fallback_when_event_framework_enabled(self, monkeypatch):
        from nodes.trigger.chat_trigger import _events
        from services import event_waiter
        from services.events import dispatch as dispatch_mod

        emit_calls: List[Any] = []
        legacy_calls: List[Any] = []

        async def fake_emit(event, **kwargs):
            emit_calls.append({"event": event, **kwargs})
            return event

        async def fake_dispatch_async(event_type, payload):
            legacy_calls.append((event_type, payload))
            return 1

        monkeypatch.setattr(dispatch_mod, "emit", fake_emit)
        monkeypatch.setattr(event_waiter, "dispatch_async", fake_dispatch_async)
        monkeypatch.setattr(_events, "_event_framework_enabled", lambda: True)

        await _events.dispatch_chat_message_received(
            {
                "message": "hello",
                "session_id": "sess-1",
                "timestamp": "2026-05-14T00:00:00",
            }
        )

        assert len(emit_calls) == 1
        assert legacy_calls == []
