"""Wave 12 B4 + canary opt-in: CloudEvents factories + dispatcher for email.

Plugin-specific event emission — replaces:
  - ``event_waiter.dispatch("email_received", email_data)`` in
    ``email_receive/__init__.py``

Per RFC plugin_authoring_rfc.md §6.4: plugin-specific factories live in
the plugin folder.

Legacy ``event_type`` (``"email_received"``) is preserved on the
dispatch path so the ``emailReceive`` trigger node's ``event_type``
ClassVar still matches without a coordinated registry-side rename.

Dual-dispatch (canary opt-in, post-2026-05-15):
  - Legacy ``event_waiter.dispatch`` for the in-process collector/processor
    (still production-live for non-canary triggers).
  - Typed ``services.events.dispatch.emit`` for Temporal-durable
    ``TriggerListenerWorkflow`` consumers (when canary registry +
    ``event_framework_enabled`` are both on — both default-true).
"""

from __future__ import annotations

from typing import Any, Mapping

from services.events.envelope import WorkflowEvent


# Legacy event_type the event_waiter dispatches by; trigger nodes
# subscribe on this string (matches ``EmailReceiveNode.event_type``).
_LEGACY_EVENT_TYPE = "email_received"


# ---- Typed factory ---------------------------------------------------------


def email_message_received(email_data: Mapping[str, Any]) -> WorkflowEvent:
    """Incoming email envelope. ``subject`` is the ``message_id`` so
    consumers can dedup and correlate (subject of the MAIL message
    itself goes in ``data.subject``)."""
    payload = dict(email_data)
    message_id = payload.get("message_id") or payload.get("id")
    return WorkflowEvent(
        source="machinaos://nodes/email",
        type="com.machinaos.email.message.received",
        subject=str(message_id) if message_id else None,
        data=payload,
    )


# ---- Dispatcher wrapper ----------------------------------------------------


async def dispatch_email_received(email_data: Mapping[str, Any]) -> int:
    """Dispatch an incoming email to waiting ``emailReceive`` trigger
    nodes.

    Two delivery paths (mirrors :func:`telegram._events.dispatch_telegram_message_received`):

    1. **Legacy event_waiter waiters** via :func:`event_waiter.dispatch`
       (in-process collector/processor; still default for trigger nodes
       outside the canary registry).
    2. **Temporal-durable listeners** via
       :func:`services.events.dispatch.emit`. ``emit`` is a pass-through
       no-op when ``event_framework_enabled`` is off; otherwise it
       Visibility-queries running ``TriggerListenerWorkflow`` instances
       and signals each.

    Returns the count of legacy waiters resolved.
    """
    from services import event_waiter
    from services.events.dispatch import emit

    payload = dict(email_data)
    resolved = event_waiter.dispatch(_LEGACY_EVENT_TYPE, payload)

    # Temporal-durable fan-out (canary opt-in via
    # ``register_canary_trigger_type("emailReceive")`` in
    # ``nodes/email/__init__.py``).
    await emit(
        email_message_received(payload),
        wire_routing_key=_LEGACY_EVENT_TYPE,
    )

    return resolved


__all__ = [
    "dispatch_email_received",
    "email_message_received",
]
