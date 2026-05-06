"""Service-singleton mixin for plugin-owned long-lived services.

Replaces the per-plugin ``_instance`` + ``get_instance()`` boilerplate
that each ``nodes/<plugin>/_service.py`` currently re-implements.
Pre-T inventory (Wave 11.I plan):

- ``nodes/telegram/_service.py:TelegramService`` -- ``_instance`` + sync
  ``get_instance`` + async ``reset_instance`` (custom — disconnects).
- ``nodes/email/_service.py:EmailService`` -- ``_instance`` + sync
  ``get_instance``, no reset.
- ``nodes/browser/_service.py`` -- module-level ``_instance`` global,
  no class-level state (different shape, kept bespoke).
- ``nodes/whatsapp/_service.py`` -- supervisor-aware singleton via
  ``BaseProcessSupervisor``, kept bespoke (different lifecycle).

Subclasses get :meth:`instance` for free. They override
:meth:`reset_instance` only if there's a side effect on reset
(Telegram disconnects the bot poll loop; that stays per-plugin).
"""

from __future__ import annotations

from typing import ClassVar, Optional, TypeVar

T = TypeVar("T", bound="ServiceSingleton")


class ServiceSingleton:
    """Mixin: per-class lazy singleton.

    Each subclass that opts in gets its own ``_instance`` slot lazily
    populated on first :meth:`instance` call. The Python attribute
    rules guarantee per-class isolation (read climbs MRO, write goes
    to the immediate class), so ``A.instance()`` and ``B.instance()``
    return distinct singletons even though both inherit the same
    declaration here.

    Usage::

        class TelegramService(ServiceSingleton):
            ...

        # module-level helper consumed by handler files:
        def get_telegram_service() -> TelegramService:
            return TelegramService.instance()

    Subclasses may also override :meth:`reset_instance` to add side
    effects (e.g. tear down a bot polling loop) before clearing.
    """

    _instance: ClassVar[Optional["ServiceSingleton"]] = None

    @classmethod
    def instance(cls: type[T]) -> T:
        """Return the per-class singleton, constructing it on first call."""
        if cls.__dict__.get("_instance") is None:
            cls._instance = cls()
        return cls._instance  # type: ignore[return-value]

    @classmethod
    def reset_instance(cls) -> None:
        """Drop the cached singleton. Override for async / cleanup
        flows; the default is a sync no-side-effect clear."""
        if cls.__dict__.get("_instance") is not None:
            cls._instance = None
