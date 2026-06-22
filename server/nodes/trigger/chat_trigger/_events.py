"""CloudEvents factory + dispatch wrapper for chat_trigger.

Per RFC plugin_authoring_rfc.md §6.4: plugin-specific factories live in
the plugin folder.

Delivery uses the durable CloudEvents path when the event framework is
enabled. In the single-process legacy deployment mode, feed
``event_waiter`` directly so chatTrigger's in-process listener can spawn
workflow runs without Temporal.
"""

from __future__ import annotations

from typing import Any, Mapping

from services.events.envelope import WorkflowEvent


# Outer wire-routing key. Matches ``ChatTriggerNode.event_type`` and the
# FE WS channel; the inner envelope carries
# ``com.machinaos.chat.message.received``.
_WIRE_ROUTING_KEY = "chat_message_received"


def chat_message_received(event_data: Mapping[str, Any]) -> WorkflowEvent:
    """Incoming chat message envelope. ``subject`` is the session_id so
    consumers can route per-conversation."""
    payload = dict(event_data)
    session_id = payload.get("session_id")
    return WorkflowEvent(
        source="machinaos://nodes/chat_trigger",
        type="com.machinaos.chat.message.received",
        subject=str(session_id) if session_id else None,
        data=payload,
    )


def _event_framework_enabled() -> bool:
    from core.config import Settings

    return bool(Settings().event_framework_enabled)


async def dispatch_chat_message_received(event_data: Mapping[str, Any]) -> None:
    """Dispatch an incoming chat message via the canary CloudEvents path."""
    from services import event_waiter
    from services.events.dispatch import emit

    payload = dict(event_data)
    await emit(
        chat_message_received(payload),
        wire_routing_key=_WIRE_ROUTING_KEY,
    )

    if not _event_framework_enabled():
        await event_waiter.dispatch_async(_WIRE_ROUTING_KEY, payload)


__all__ = [
    "chat_message_received",
    "dispatch_chat_message_received",
]
