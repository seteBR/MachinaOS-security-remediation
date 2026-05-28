"""F4.B infrastructure tests for ``AgentWorkflow`` + agent activities.

Smoke-level coverage so the worker bootstraps cleanly and the activity
shapes match what ``AgentWorkflow`` expects to schedule. Full
end-to-end testing of the agent loop (LLM step → tool dispatch →
persist → compaction) requires a Temporal test cluster + real plugin
classes — that lives in test_agent_workflow_integration.py once the
canary agent migration lands. This file locks the static contracts:

- AgentWorkflow class is decorated with ``@workflow.defn``.
- Three activities are decorated with ``@activity.defn`` and carry the
  expected ``node`` names.
- ``collect_agent_activities()`` returns them in a stable order.
- The orchestrator's worker registration imports both without error.
"""

from __future__ import annotations


class TestAgentWorkflowDefinition:
    """``AgentWorkflow`` must be a valid Temporal workflow definition
    so workers can register it."""

    def test_class_is_workflow_defn(self):
        from services.temporal.agent_workflow import AgentWorkflow

        # ``@workflow.defn`` attaches metadata as ``__temporal_workflow_definition``.
        defn = getattr(AgentWorkflow, "__temporal_workflow_definition", None)
        assert defn is not None, "AgentWorkflow missing @workflow.defn"
        assert defn.name == "AgentWorkflow"

    def test_class_is_sandboxed_false(self):
        """Workflow needs to import frozen registry dicts deterministically
        (for tool type → activity name resolution). Sandboxing must be off
        — same as MachinaWorkflow."""
        from services.temporal.agent_workflow import AgentWorkflow

        defn = getattr(AgentWorkflow, "__temporal_workflow_definition")
        assert defn.sandboxed is False, "AgentWorkflow must be sandboxed=False so it can read " "services.node_registry deterministically"


class TestAgentActivities:
    """The three agent activities must register under stable names so
    ``AgentWorkflow`` can schedule them by string."""

    def test_execute_llm_step_registered(self):
        from services.temporal.agent_activities import execute_llm_step

        defn = getattr(execute_llm_step, "__temporal_activity_definition", None)
        assert defn is not None
        assert defn.name == "agent.execute_llm_step.v1"

    def test_persist_agent_turn_registered(self):
        from services.temporal.agent_activities import persist_agent_turn

        defn = getattr(persist_agent_turn, "__temporal_activity_definition")
        assert defn.name == "agent.persist_turn.v1"

    def test_compact_agent_memory_registered(self):
        from services.temporal.agent_activities import compact_agent_memory

        defn = getattr(compact_agent_memory, "__temporal_activity_definition")
        assert defn.name == "agent.compact_memory.v1"

    def test_collect_returns_all_seven(self):
        """Each successive sprint added one F4.B agent activity:
        infra (3) → per-agent-wiring +prepare_payload (4) → CloudEvents
        cleanup +broadcast_progress (5) → +store_output (6) →
        +refresh_tools (7). All must register so the AgentWorkflow loop
        can schedule them by name."""
        from services.temporal.agent_activities import collect_agent_activities

        activities = collect_agent_activities()
        names = sorted(getattr(a, "__temporal_activity_definition").name for a in activities)
        assert names == [
            "agent.broadcast_progress.v1",
            "agent.compact_memory.v1",
            "agent.execute_llm_step.v1",
            "agent.persist_turn.v1",
            "agent.prepare_payload.v1",
            "agent.refresh_tools.v1",
            "agent.store_output.v1",
        ]

    def test_prepare_payload_registered(self):
        from services.temporal.agent_activities import prepare_agent_payload

        defn = getattr(prepare_agent_payload, "__temporal_activity_definition")
        assert defn.name == "agent.prepare_payload.v1"

    def test_broadcast_progress_registered(self):
        from services.temporal.agent_activities import broadcast_agent_progress

        defn = getattr(broadcast_agent_progress, "__temporal_activity_definition")
        assert defn.name == "agent.broadcast_progress.v1"


class TestWorkerWiring:
    """Worker registration must include AgentWorkflow + activities so the
    orchestrator can schedule them once the flag flips on. We can't
    spin up a real Temporal client here, but we can verify the
    registration list is built without import errors."""

    def test_agent_workflow_importable_from_worker(self):
        """The worker module imports AgentWorkflow at registration time.
        If that import fails (circular dep, missing symbol, etc.) the
        whole Temporal worker bootstrap dies — catch it here."""
        # Just importing is enough; ImportError would surface in the test
        # output.
        from services.temporal.worker import TemporalWorkerManager  # noqa: F401
        from services.temporal.agent_workflow import AgentWorkflow  # noqa: F401
        from services.temporal.agent_activities import collect_agent_activities  # noqa: F401


class TestPayloadShape:
    """Static checks on the workflow's payload contract — keeps the
    seams visible to anyone refactoring the input pipeline. If a
    required key disappears, this test surfaces it before runtime."""

    REQUIRED_KEYS = (
        "node_id",
        "node_type",
        "provider",
        "model",
        "api_key",
        "system_message",
        "user_prompt",
        "tools",
        "max_iterations",
    )

    def test_required_keys_documented(self):
        """The README-style payload comment in ``AgentWorkflow.run``'s
        docstring must list every required key. Drift = unreadable
        docs + broken callers. Cross-check against an explicit
        constant here so the docstring can't quietly shrink."""
        from services.temporal.agent_workflow import AgentWorkflow

        docstring = AgentWorkflow.run.__doc__ or ""
        missing = [k for k in self.REQUIRED_KEYS if f'"{k}"' not in docstring]
        assert not missing, (
            f"AgentWorkflow.run docstring missing payload keys: {missing}. "
            "If you renamed a field, update both the docstring and the body."
        )


class TestDelegationToolDispatch:
    """Regression: when the LLM emits a ``delegate_to_<child>`` tool
    call inside ``AgentWorkflow``'s tool-dispatch loop, the resulting
    activity payload MUST:

    1. Remap ``args.task → node_data.system_message`` and
       ``args.context → node_data.prompt`` so the child agent's
       ``Params`` model picks them up. Pre-fix the workflow merged
       ``call.args`` (``{task, context}``) into ``node_data`` as-is —
       ``SpecializedAgentParams`` doesn't have those fields, so the
       child got empty prompt/system_message and Gemini failed with
       ``contents are required``.
    2. Carry the full canvas (``nodes`` + ``edges``) so the child's
       ``collect_agent_connections`` edge walk finds its connected
       skills / memory / tools. Pre-fix this was ``[]`` / ``[]`` for
       every tool call — fine for regular tools but broken for
       delegation.

    Source-introspection invariant — runtime test against the live
    workflow body needs a Temporal WorkflowEnvironment which is too
    heavy for unit tests. The source check is enough to lock the
    behaviour against regression.
    """

    def test_dispatch_remaps_delegation_args(self):
        import inspect

        from services.temporal.agent_workflow import AgentWorkflow

        src = inspect.getsource(AgentWorkflow.run)

        # Detection: must check for the ``delegate_to_`` tool-name prefix.
        assert "delegate_to_" in src, (
            "AgentWorkflow tool dispatch lost the ``delegate_to_`` "
            "detection branch. Without it, delegation tool calls take "
            "the regular-tool path which leaves the child agent's "
            "``prompt`` + ``system_message`` empty and Gemini fails "
            "with ``contents are required``."
        )
        # Remapping: task → system_message, context → prompt.
        assert "system_message" in src and "task" in src and "prompt" in src, (
            "AgentWorkflow tool dispatch must map the LLM's "
            "``{task, context}`` args to the child agent's "
            "``{system_message, prompt}`` Params. Same mapping the "
            "legacy ``_execute_delegated_agent`` applies."
        )

    def test_dispatch_passes_canvas_for_delegation(self):
        """Delegation tool calls must pass the parent's ``nodes`` +
        ``edges`` to the child agent's activity so the child's edge
        walk can find its skills/memory/tools. Regular tool calls
        keep the empty-canvas optimisation."""
        import inspect

        from services.temporal.agent_workflow import AgentWorkflow

        src = inspect.getsource(AgentWorkflow.run)

        # The fix uses ``context.get("nodes")`` / ``context.get("edges")``
        # inside the delegation branch.
        assert 'context.get("nodes")' in src, (
            "AgentWorkflow tool dispatch must read ``context.get('nodes')`` "
            "to pass the canvas to delegation tool calls. Without it, "
            "the child agent's edge walk sees an empty graph and can't "
            "resolve its connected skills / memory / tools."
        )
        assert 'context.get("edges")' in src, (
            "AgentWorkflow tool dispatch must read ``context.get('edges')`` "
            "for the same reason — both are needed by "
            "``collect_agent_connections``."
        )


class TestAutoRebindTools:
    """Mid-run tool rebind after canvas-mutating tools return
    ``operations`` (workflow_ops batch). The flag is read once in
    ``prepare_agent_payload``, forwarded into every tool's payload, and
    surfaced into ``ctx.raw["auto_rebind_tools"]`` so agentBuilder's
    summary text reflects the user's preference. The rebind itself
    happens in ``AgentWorkflow.run`` via a new
    ``agent.refresh_tools.v1`` activity.
    """

    def test_refresh_tools_activity_registered(self):
        from services.temporal.agent_activities import refresh_agent_tools

        defn = getattr(refresh_agent_tools, "__temporal_activity_definition", None)
        assert defn is not None, "refresh_agent_tools missing @activity.defn"
        assert defn.name == "agent.refresh_tools.v1"

    def test_refresh_tools_in_collect(self):
        """Worker registration must include the new activity so
        AgentWorkflow can schedule it."""
        from services.temporal.agent_activities import collect_agent_activities, refresh_agent_tools

        names = {getattr(a, "__temporal_activity_definition").name for a in collect_agent_activities()}
        assert "agent.refresh_tools.v1" in names
        assert refresh_agent_tools in collect_agent_activities()

    def test_workflow_calls_refresh_after_ops(self):
        """AgentWorkflow.run must schedule ``agent.refresh_tools.v1``
        when a tool result carries an ``operations`` field."""
        import inspect

        from services.temporal.agent_workflow import AgentWorkflow

        src = inspect.getsource(AgentWorkflow.run)
        assert '"agent.refresh_tools.v1"' in src, (
            "AgentWorkflow tool dispatch must schedule agent.refresh_tools.v1 "
            "when a tool result returns workflow_ops operations."
        )
        # The rebind branch must extend `tools` and `tool_index` so the
        # next execute_llm_step iteration sees the new tools.
        assert "tools.append" in src or "tools.extend" in src, (
            "AgentWorkflow must extend its tools list after refresh."
        )
        assert "tool_index[" in src, "AgentWorkflow must extend tool_index after refresh."

    def test_prepare_payload_surfaces_auto_rebind_flag(self):
        """prepare_agent_payload reads the UserSettings flag and includes
        ``auto_rebind_tools`` in its returned payload so AgentWorkflow
        + the tool dispatch see the user's preference."""
        import inspect

        from services.temporal.agent_activities import prepare_agent_payload

        src = inspect.getsource(prepare_agent_payload)
        assert "auto_rebind_tools_after_canvas_change" in src, (
            "prepare_agent_payload must read the user setting."
        )
        assert '"auto_rebind_tools"' in src, (
            "prepare_agent_payload return must include the resolved flag."
        )

    def test_tool_payload_forwards_auto_rebind(self):
        """The per-tool activity payload must forward
        ``auto_rebind_tools`` so the F4.A wrapper can land it into
        ctx.raw for agentBuilder's summary text."""
        import inspect

        from services.temporal.agent_workflow import AgentWorkflow

        src = inspect.getsource(AgentWorkflow.run)
        assert '"auto_rebind_tools"' in src, (
            "AgentWorkflow tool_payload must include auto_rebind_tools "
            "so the per-tool activity surfaces it into ctx.raw."
        )


class TestNeedsCanvasDispatch:
    """Regression: regular (non-delegation) tools opt into canvas
    propagation via the ``BaseNode.needs_canvas`` ClassVar. The F4.B
    tool-dispatch path must read the flag via
    ``services.node_registry.get_node_class`` rather than hardcoding
    per-plugin type strings. Locks the principled fix for the
    agentBuilder ``nodes=0 edges=0`` bug.
    """

    def test_dispatch_uses_get_node_class_lookup(self):
        """The non-delegation branch must look the plugin class up at
        dispatch time so ``cls.needs_canvas`` decides canvas
        propagation. A hardcoded type-string check would silently break
        for any future canvas-aware tool."""
        import inspect

        from services.temporal.agent_workflow import AgentWorkflow

        src = inspect.getsource(AgentWorkflow.run)
        assert "get_node_class(" in src, (
            "AgentWorkflow tool dispatch must call ``get_node_class("
            "tool_info['node_type'])`` so it can read the plugin's "
            "``needs_canvas`` ClassVar. Hardcoded type-string checks "
            "are forbidden — they don't compose for future canvas-"
            "aware tools."
        )
        assert "needs_canvas" in src, (
            "AgentWorkflow tool dispatch must read the resolved "
            "``plugin_cls.needs_canvas`` flag. Without it the canvas "
            "never reaches agentBuilder and ``_resolve_caller`` falls "
            "back to self-as-caller."
        )

    def test_get_node_class_imported_at_module_level(self):
        """The helper must be importable from the workflow module
        — Temporal's ``@workflow.defn(sandboxed=False)`` lets us touch
        ``services.node_registry`` deterministically."""
        from services.temporal import agent_workflow

        assert hasattr(agent_workflow, "get_node_class"), (
            "agent_workflow.py must import ``get_node_class`` at module "
            "level so the workflow body can resolve plugin classes by "
            "type string."
        )
