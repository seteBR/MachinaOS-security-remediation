from .._specialized import SpecializedAgentBase


class AutonomousAgentNode(SpecializedAgentBase):
    type = "autonomous_agent"
    display_name = "Autonomous Agent"
    subtitle = "Autonomous Ops"
    group = ("agent",)
    description = "Autonomous agent using Code Mode patterns"
    tool_description = "ONE-SHOT delegation to Autonomous Agent. Call ONCE per task, returns task_id. Agent works in background using Code Mode patterns - do NOT re-call."
