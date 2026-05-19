"""Plugins for the 'location' palette group. See ../__init__.py for the package layout.

Self-registration on import:
  - Wave 12 C4 sub-piece C: ``MapsService`` is published as the
    ``"maps"`` service factory via
    ``services.plugin.service_factories.register_service_factory``.
    The DI container's ``maps_service`` provider looks up the factory
    at instantiation time, so the framework no longer carries a
    top-level ``from nodes.location._service import MapsService``.
  - Eager-import the three gmaps subpackages so their ``BaseNode``
    subclasses auto-register regardless of ``pkgutil.walk_packages``
    recursion behaviour. The conftest plugin-discovery path was
    occasionally skipping nested subpackages on CI Linux; this
    belt-and-braces approach makes the registration deterministic.
"""

from core.logging import get_logger
from services.plugin.service_factories import register_service_factory

from ._service import MapsService

logger = get_logger(__name__)

# Diagnostic block: the previous CI run silently dropped the three
# gmaps registrations even though the eager imports below appeared
# to run. Log NODE_METADATA membership on either side of the eager
# imports so the next CI run reveals which side of the registration
# is broken. Remove once diagnosed.
import sys as _sys

logger.info(
    "[location] pre-eager-import sys.modules: "
    "gmaps_create=%s gmaps_locations=%s gmaps_nearby_places=%s",
    "nodes.location.gmaps_create" in _sys.modules,
    "nodes.location.gmaps_locations" in _sys.modules,
    "nodes.location.gmaps_nearby_places" in _sys.modules,
)
try:
    from . import gmaps_create as _gmaps_create  # noqa: F401 — registers GmapsCreateNode
    from . import gmaps_locations as _gmaps_locations  # noqa: F401 — registers GmapsLocationsNode
    from . import gmaps_nearby_places as _gmaps_nearby_places  # noqa: F401 — registers GmapsNearbyPlacesNode
    logger.info("[location] eager imports succeeded")
except Exception:
    logger.exception("[location] eager imports raised")

from models.node_metadata import NODE_METADATA as _NM

logger.info(
    "[location] post-eager-import NODE_METADATA: "
    "gmaps_create=%s gmaps_locations=%s gmaps_nearby_places=%s",
    "gmaps_create" in _NM,
    "gmaps_locations" in _NM,
    "gmaps_nearby_places" in _NM,
)

register_service_factory("maps", MapsService)
