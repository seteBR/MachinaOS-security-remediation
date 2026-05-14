"""Contract tests for ``services.workflow_validator.validate_workflow``.

Locks the six issue codes the validator surfaces:

- ``DANGLING_EDGE`` — edge references a node id that isn't in the graph.
- ``UNKNOWN_NODE_TYPE`` — plugin not installed on this instance.
- ``INVALID_PARAM`` — Pydantic ``Params.model_validate`` raises.
- ``MISSING_CREDENTIAL`` — declared credential not stored.
- ``CYCLE`` — Kahn's algorithm leaves nodes unresolved.
- Empty report — valid workflow returns ``{errors: [], warnings: []}``.

Used to gate ``handle_execute_workflow`` (force=False), all
``handle_deploy_workflow`` calls, and ``example_loader.import_examples_for_user``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes — a small in-memory plugin registry so tests are deterministic and
# don't depend on which plugins happen to be installed at run time.
# ---------------------------------------------------------------------------


class _FakeCredential:
    id = "fake_provider"
    auth = "api_key"


class _FakeParams(BaseModel):
    text: str = Field(..., min_length=1)


class _FakeNodeClass:
    type = "fakeNode"
    Params = _FakeParams
    credentials = (_FakeCredential,)


class _FakeNodelessClass:
    """Plugin with no credentials and a permissive Params (every workflow
    invariant is honored)."""

    type = "fakeNodeless"

    class Params(BaseModel):
        pass

    credentials = ()


def _patch_registry(monkeypatch, mapping: dict[str, object]) -> None:
    """Patch ``get_node_class`` to return our fakes."""
    monkeypatch.setattr(
        "services.workflow_validator.get_node_class",
        lambda node_type: mapping.get(node_type),
    )


def _patch_auth(monkeypatch, has_valid_key_return: bool) -> None:
    """Patch the container so ``auth_service.has_valid_key`` returns a fixed bool."""
    fake_auth = MagicMock()
    fake_auth.has_valid_key = AsyncMock(return_value=has_valid_key_return)
    fake_container = MagicMock()
    fake_container.auth_service.return_value = fake_auth
    monkeypatch.setattr("core.container.container", fake_container)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_dangling_edge_target_is_error(monkeypatch):
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNodeless": _FakeNodelessClass})
    _patch_auth(monkeypatch, True)

    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "fakeNodeless", "data": {}}],
        edges=[{"id": "e1", "source": "n1", "target": "ghost"}],
    )
    codes = [iss["code"] for iss in report["errors"]]
    assert "DANGLING_EDGE" in codes


async def test_dangling_edge_source_is_error(monkeypatch):
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNodeless": _FakeNodelessClass})
    _patch_auth(monkeypatch, True)

    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "fakeNodeless", "data": {}}],
        edges=[{"id": "e1", "source": "ghost", "target": "n1"}],
    )
    codes = [iss["code"] for iss in report["errors"]]
    assert "DANGLING_EDGE" in codes


async def test_unknown_node_type_is_error(monkeypatch):
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {})
    _patch_auth(monkeypatch, True)

    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "doesNotExist", "data": {}}],
        edges=[],
    )
    codes = [iss["code"] for iss in report["errors"]]
    assert "UNKNOWN_NODE_TYPE" in codes
    issue = next(iss for iss in report["errors"] if iss["code"] == "UNKNOWN_NODE_TYPE")
    assert issue["node_id"] == "n1"
    assert issue["node_type"] == "doesNotExist"


async def test_invalid_param_is_warning(monkeypatch):
    """INVALID_PARAM is a WARNING — matches the runtime soft-fail at
    ``node_executor._prepare_parameters`` (logs WARN, continues)."""
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNode": _FakeNodeClass})
    _patch_auth(monkeypatch, True)

    # text is required + min_length=1; empty triggers ValidationError.
    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "fakeNode", "data": {"parameters": {"text": ""}}}],
        edges=[],
    )
    codes = [iss["code"] for iss in report["warnings"]]
    assert "INVALID_PARAM" in codes
    assert all(iss["code"] != "INVALID_PARAM" for iss in report["errors"]), (
        "INVALID_PARAM must not block execution; only deploy-time errors block."
    )


async def test_missing_credential_is_warning(monkeypatch):
    """MISSING_CREDENTIAL is a WARNING so the workflow can be saved/imported
    and credentials configured afterward. Runtime failure (different path,
    different broadcast) is what surfaces to the user during execution."""
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNode": _FakeNodeClass})
    _patch_auth(monkeypatch, False)  # credential NOT stored

    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "fakeNode", "data": {"parameters": {"text": "ok"}}}],
        edges=[],
    )
    codes = [iss["code"] for iss in report["warnings"]]
    assert "MISSING_CREDENTIAL" in codes
    issue = next(iss for iss in report["warnings"] if iss["code"] == "MISSING_CREDENTIAL")
    assert issue["provider_id"] == "fake_provider"
    assert issue["remediation"] == "add_key"
    assert issue["node_id"] == "n1"


async def test_cycle_is_error(monkeypatch):
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNodeless": _FakeNodelessClass})
    _patch_auth(monkeypatch, True)

    # Two-node cycle: n1 -> n2 -> n1
    report = await validate_workflow(
        nodes=[
            {"id": "n1", "type": "fakeNodeless", "data": {}},
            {"id": "n2", "type": "fakeNodeless", "data": {}},
        ],
        edges=[
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n1"},
        ],
    )
    codes = [iss["code"] for iss in report["errors"]]
    assert "CYCLE" in codes
    cycle = next(iss for iss in report["errors"] if iss["code"] == "CYCLE")
    assert set(cycle["nodes"]) == {"n1", "n2"}


async def test_valid_workflow_returns_empty_report(monkeypatch):
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNodeless": _FakeNodelessClass})
    _patch_auth(monkeypatch, True)

    report = await validate_workflow(
        nodes=[
            {"id": "n1", "type": "fakeNodeless", "data": {}},
            {"id": "n2", "type": "fakeNodeless", "data": {}},
        ],
        edges=[{"id": "e1", "source": "n1", "target": "n2"}],
    )
    assert report == {"errors": [], "warnings": []}


async def test_parameters_by_id_overrides_node_data(monkeypatch):
    """When parameters_by_id is supplied, it wins over node.data.parameters.
    Used by the WS execute handler (hydrating from DB) and the
    example_loader (which holds params in the JSON's nodeParameters block)."""
    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {"fakeNode": _FakeNodeClass})
    _patch_auth(monkeypatch, True)

    # node.data has valid params, parameters_by_id has invalid → invalid wins.
    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "fakeNode", "data": {"parameters": {"text": "good"}}}],
        edges=[],
        parameters_by_id={"n1": {"text": ""}},
    )
    codes = [iss["code"] for iss in report["warnings"]]
    assert "INVALID_PARAM" in codes


async def test_report_shape_is_plain_dicts(monkeypatch):
    """Issues must be plain dicts (no dataclasses / enums) so the report
    serializes directly to JSON without custom encoders."""
    import json

    from services.workflow_validator import validate_workflow

    _patch_registry(monkeypatch, {})
    _patch_auth(monkeypatch, True)

    report = await validate_workflow(
        nodes=[{"id": "n1", "type": "unknown", "data": {}}],
        edges=[],
    )
    # Should round-trip through stdlib JSON without errors.
    serialized = json.dumps(report)
    assert "UNKNOWN_NODE_TYPE" in serialized


# ---------------------------------------------------------------------------
# WS-handler gating invariants
# ---------------------------------------------------------------------------


class TestExecuteAndDeployHandlersGate:
    """Static-source contract: ``handle_execute_workflow`` and
    ``handle_deploy_workflow`` MUST call ``validate_workflow`` before
    handing the graph off to ``WorkflowService``. Anchor on the function
    name string so a rename forces a deliberate test update.
    """

    @staticmethod
    def _handler_source(handler) -> str:
        import inspect

        fn = handler
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return inspect.getsource(fn)

    def test_execute_workflow_calls_validator(self):
        from routers import websocket as ws_module

        src = self._handler_source(ws_module.handle_execute_workflow)
        assert "validate_workflow" in src, (
            "handle_execute_workflow must call validate_workflow so "
            "broken workflows are blocked at the gate (force=true overrides)."
        )
        assert "force" in src, (
            "handle_execute_workflow must support the force=true override "
            "so 'Run anyway' can bypass warnings (Windmill pattern)."
        )

    def test_deploy_workflow_calls_validator_unconditionally(self):
        from routers import websocket as ws_module

        src = self._handler_source(ws_module.handle_deploy_workflow)
        assert "validate_workflow" in src, (
            "handle_deploy_workflow must call validate_workflow — a broken "
            "workflow deployed on a schedule is much worse than a failed "
            "manual run, so deploy never honors a force-override."
        )

    def test_validate_workflow_handler_registered(self):
        from routers import websocket as ws_module

        assert "validate_workflow" in ws_module.MESSAGE_HANDLERS, (
            "validate_workflow message type must be in MESSAGE_HANDLERS "
            "so the frontend live-lint and import dry-run paths can reach it."
        )

    def test_example_loader_calls_validator(self):
        """First-launch example import must run validator to skip
        malformed examples (errors) and log credential gaps (warnings)."""
        import inspect
        from services import example_loader

        src = inspect.getsource(example_loader.import_examples_for_user)
        assert "validate_workflow" in src, (
            "import_examples_for_user must run validate_workflow before "
            "save_workflow — broken examples shipped on disk are bugs."
        )
