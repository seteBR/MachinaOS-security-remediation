"""Prompt/tool-injection guardrail tests for LangChain agent paths."""

from __future__ import annotations

import inspect

from services import ai as ai_module
from services.ai import AIService


class TestPromptToolSecurityGuardrail:
    def test_guardrail_appends_once(self):
        original = "You are a helpful assistant."

        first = ai_module._with_prompt_tool_security_guardrail(original)
        second = ai_module._with_prompt_tool_security_guardrail(first)

        assert first.startswith(original)
        assert first.count("## Prompt And Tool Security") == 1
        assert second == first

    def test_guardrail_names_untrusted_surfaces_and_secret_limits(self):
        text = ai_module._with_prompt_tool_security_guardrail("")

        for surface in (
            "user prompts",
            "memory",
            "tool results",
            "web pages",
            "file contents",
        ):
            assert surface in text

        for forbidden_goal in (
            "reveal secrets",
            "expose credentials",
            "API keys or tokens",
            "broaden tool permissions",
        ):
            assert forbidden_goal in text

    def test_execute_agent_injects_guardrail_after_tool_guidance(self):
        src = inspect.getsource(AIService.execute_agent)

        guardrail_pos = src.index("_with_prompt_tool_security_guardrail(system_message)")
        insert_pos = src.index("initial_messages.insert(0, SystemMessage")

        assert guardrail_pos < insert_pos

    def test_execute_chat_agent_injects_guardrail_before_messages(self):
        src = inspect.getsource(AIService.execute_chat_agent)

        guardrail_pos = src.index("_with_prompt_tool_security_guardrail(system_message)")
        append_pos = src.index("messages.append(SystemMessage")

        assert guardrail_pos < append_pos
