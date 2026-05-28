"""ToolNode — passive capability exposed to AI Agents via input-tools.

Return shape differs from :class:`ActionNode`: the LLM harness expects a
flat dict (no ``success`` wrapper). ``.as_tool_schema()`` produces the
JSON Schema the LLM sees — derived from :class:`Params` automatically.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Optional

from services.plugin.base import BaseNode
from services.plugin.scaling import TaskQueue


class ToolNode(BaseNode, abstract=True):
    """Base class for AI-Agent tool nodes (calculatorTool, currentTimeTool)."""

    component_kind: ClassVar[str] = "tool"
    task_queue: ClassVar[str] = TaskQueue.REST_API

    # Tool-safety annotations (Pipedream pattern).
    annotations: ClassVar[Dict[str, Any]] = {
        "destructive": False,
        "readonly": True,
        "open_world": False,
    }

    @classmethod
    def as_tool_schema(cls) -> Dict[str, Any]:
        """LLM-visible schema: ``{name, description, parameters}`` where
        ``parameters`` is the Pydantic JSON schema of :class:`Params`."""
        schema = cls.Params.model_json_schema()
        # Strip $defs / definitions — LLM function-calling doesn't cope.
        schema.pop("$defs", None)
        schema.pop("definitions", None)
        return {
            "name": cls.type,
            "description": cls.description or cls.display_name or cls.type,
            "parameters": schema,
        }

    def _wrap_success(self, *, start_time: float, result):
        """Tools return flat result (no success wrapper)."""
        from pydantic import BaseModel

        if isinstance(result, BaseModel):
            return result.model_dump()
        if isinstance(result, dict):
            return result
        return {"result": result}

    @classmethod
    def interpret_result(cls, result: Dict[str, Any]) -> tuple[bool, Any, Optional[str]]:
        """ToolNode contract: a flat dict (no ``success`` key) IS the
        success payload. Operation exceptions still flow through
        :meth:`_wrap_error` and produce the standard envelope — those
        get the base-class semantics."""
        if isinstance(result, dict) and "success" not in result:
            return True, result, None
        return super().interpret_result(result)
