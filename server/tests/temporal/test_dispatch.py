"""F4.A: per-type activity dispatch resolver invariants.

Locks the orchestrator's `_resolve_activity` contract:
  - flag OFF (default): every node routes to legacy `execute_node_activity`
  - flag ON + registered plugin: routes to `node.{type}.v{version}`
  - flag ON + unknown type: falls back to legacy
  - task_queue is always None (per-queue routing waits for TemporalWorkerPool)

If these invariants drift the Temporal worker will either silently lose
per-type activity wiring (regression to single-dispatcher) or schedule
activities on queues no worker polls (workflow hangs). Same coverage
pattern as test_credential_broadcasts / test_status_broadcasts —
introspect the class, exercise the method, assert the shape.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import nodes  # noqa: F401 -- triggers plugin discovery
from services.temporal.workflow import MachinaWorkflow


@pytest.fixture
def workflow_instance() -> MachinaWorkflow:
    return MachinaWorkflow()


def _set_flag(value: bool):
    """Patch the ``Settings`` import used by ``_resolve_activity``.

    ``tests/conftest.py`` stubs ``core.config.Settings`` as a MagicMock,
    so we can't go through the real env var. Instead, swap the lazy
    import inside the resolver for a SimpleNamespace returning the
    desired flag value. Same effective contract — the resolver only
    reads ``Settings().temporal_per_type_dispatch``.
    """

    def fake_settings_factory():
        return SimpleNamespace(temporal_per_type_dispatch=value)

    return patch("core.config.Settings", side_effect=lambda: fake_settings_factory())


class TestResolveActivityFlagOff:
    """Default behavior: legacy dispatcher for every node, no surprises."""

    def test_known_plugin_routes_to_legacy(self, workflow_instance):
        with _set_flag(False):
            name, queue = workflow_instance._resolve_activity("pythonExecutor")
        assert name == "execute_node_activity"
        assert queue is None

    def test_unknown_type_routes_to_legacy(self, workflow_instance):
        with _set_flag(False):
            name, queue = workflow_instance._resolve_activity("nonExistentType")
        assert name == "execute_node_activity"
        assert queue is None

    def test_agent_routes_to_legacy(self, workflow_instance):
        with _set_flag(False):
            name, queue = workflow_instance._resolve_activity("aiAgent")
        assert name == "execute_node_activity"
        assert queue is None


class TestResolveActivityFlagOn:
    """Flag on: per-type for registered plugins, legacy fallback otherwise."""

    def test_known_plugin_routes_per_type(self, workflow_instance):
        with _set_flag(True):
            name, queue = workflow_instance._resolve_activity("pythonExecutor")
        assert name == "node.pythonExecutor.v1"
        # F4.A intentionally returns None for queue — per-queue routing
        # depends on TemporalWorkerPool which isn't wired yet.
        assert queue is None

    def test_agent_routes_per_type(self, workflow_instance):
        with _set_flag(True):
            name, queue = workflow_instance._resolve_activity("aiAgent")
        assert name == "node.aiAgent.v1"
        assert queue is None

    def test_unknown_type_falls_back_to_legacy(self, workflow_instance):
        with _set_flag(True):
            name, queue = workflow_instance._resolve_activity("nonExistentType")
        assert name == "execute_node_activity"
        assert queue is None

    def test_specialized_agent_uses_class_version(self, workflow_instance):
        """All 117 plugins default to version=1; the activity name must
        include the version. If a plugin ever overrides cls.version, this
        test catches the schema break-point."""
        with _set_flag(True):
            name, _ = workflow_instance._resolve_activity("coding_agent")
        assert name.startswith("node.coding_agent.v")
        # Extract version; should match the class's declared version.
        from services.node_registry import get_node_class
        cls = get_node_class("coding_agent")
        assert name == f"node.coding_agent.v{cls.version}"


class TestPerTypeActivityCollection:
    """`collect_plugin_activities()` must return one callable per registered
    plugin class — TemporalWorkerManager's per-type registration depends on
    this returning the full set, not a queue-filtered subset (F4.A puts
    all per-type entries on the default queue until TemporalWorkerPool
    lands)."""

    def test_collect_returns_one_per_plugin(self):
        from services.node_registry import registered_node_classes
        from services.temporal.plugin_activities import collect_plugin_activities

        activities = collect_plugin_activities()
        # Per-type activity count must equal registered plugin count.
        assert len(activities) == len(registered_node_classes())

    def test_per_type_activity_has_temporal_metadata(self):
        """Every per-type activity must carry the @activity.defn decorator
        with a `node.{type}.v{version}` name — otherwise the worker can't
        register it."""
        from services.temporal.plugin_activities import collect_plugin_activities

        activities = collect_plugin_activities()
        for a in activities:
            # temporalio attaches metadata as `__temporal_activity_definition`.
            defn = getattr(a, "__temporal_activity_definition", None)
            assert defn is not None, f"activity {a} missing Temporal defn"
            assert defn.name.startswith("node."), defn.name
            assert ".v" in defn.name, defn.name
