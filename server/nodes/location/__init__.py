"""Plugins for the 'location' palette group. See ../__init__.py for the package layout.

Self-registration on import:
  - Wave 12 C4 sub-piece C: ``MapsService`` is published as the
    ``"maps"`` service factory via
    ``services.plugin.service_factories.register_service_factory``.
    The DI container's ``maps_service`` provider looks up the factory
    at instantiation time, so the framework no longer carries a
    top-level ``from nodes.location._service import MapsService``.
"""

from services.plugin.service_factories import register_service_factory

from ._service import MapsService

register_service_factory("maps", MapsService)
