"""Locks the chat-model dual-purpose scope per the advisor-strategy plan.

Exactly three chat-model plugins (anthropic / openai / gemini) are wired
as standard dual-purpose tools. The other 8 chat-model plugins (groq /
cerebras / deepseek / kimi / mistral / openrouter / xai / ollama / lmstudio)
remain single-purpose. Adding usable_as_tool=True to one of the latter
without explicit plan approval should fail this test.
"""

from __future__ import annotations


def _all_chat_model_classes():
    """All ChatModelBase subclasses, sourced from the live plugin registry."""
    import nodes  # noqa: F401  (populate registry)
    from services.node_registry import registered_node_classes
    from nodes.model._base import ChatModelBase

    return [
        cls
        for cls in registered_node_classes().values()
        if isinstance(cls, type)
        and issubclass(cls, ChatModelBase)
        and cls is not ChatModelBase
    ]


_ADVISOR_SUPPORTED = frozenset(
    {"anthropicChatModel", "openaiChatModel", "geminiChatModel"}
)


class TestAdvisorChatModelScope:
    """The dual-purpose marker is set on exactly the three supported plugins."""

    def test_supported_plugins_are_tool_eligible(self):
        by_type = {cls.type: cls for cls in _all_chat_model_classes()}
        for node_type in _ADVISOR_SUPPORTED:
            cls = by_type.get(node_type)
            assert cls is not None, f"Expected chat-model plugin {node_type!r} not in registry"
            assert cls.usable_as_tool is True, (
                f"{cls.__qualname__} must set usable_as_tool=True per the advisor plan"
            )
            assert "tool" in cls.group, (
                f"{cls.__qualname__}.group must contain 'tool' "
                f"(found {cls.group!r}) for palette + dual-purpose dispatch"
            )

    def test_other_chat_models_are_not_tool_eligible(self):
        """Lock the V1 scope: the other 8 chat-models stay single-purpose."""
        for cls in _all_chat_model_classes():
            if cls.type in _ADVISOR_SUPPORTED:
                continue
            assert cls.usable_as_tool is False, (
                f"{cls.__qualname__} (type={cls.type!r}) sets usable_as_tool=True "
                f"but is not in the advisor-strategy supported list "
                f"{sorted(_ADVISOR_SUPPORTED)}. Update the plan + this test together."
            )
            assert "tool" not in cls.group, (
                f"{cls.__qualname__} (type={cls.type!r}) has 'tool' in group "
                f"but is not in the supported list. Same scope rule applies."
            )


class TestAdvisorToolNames:
    """The supported plugins use the snake_case-of-type convention per GUIDE.md."""

    EXPECTED = {
        "anthropicChatModel": "anthropic_chat_model",
        "openaiChatModel": "openai_chat_model",
        "geminiChatModel": "gemini_chat_model",
    }

    def test_tool_names_match_snake_case_convention(self):
        by_type = {cls.type: cls for cls in _all_chat_model_classes()}
        for node_type, expected_tool_name in self.EXPECTED.items():
            cls = by_type[node_type]
            assert cls.tool_name == expected_tool_name, (
                f"{cls.__qualname__}.tool_name = {cls.tool_name!r} "
                f"but expected {expected_tool_name!r} (snake_case of type)"
            )


class TestAdvisorSkillShipped:
    """The advisor skill must be shipped on disk and discoverable."""

    def test_advisor_skill_exists_on_disk(self):
        from pathlib import Path

        skill_md = (
            Path(__file__).parent.parent
            / "skills"
            / "assistant"
            / "advisor"
            / "SKILL.md"
        )
        assert skill_md.is_file(), (
            f"Advisor skill missing at {skill_md}. "
            "Ship server/skills/assistant/advisor/SKILL.md per the advisor plan."
        )

    def test_advisor_skill_lists_supported_tools(self):
        """`allowed-tools` frontmatter mirrors the supported plugins."""
        from pathlib import Path
        import re

        skill_md = (
            Path(__file__).parent.parent
            / "skills"
            / "assistant"
            / "advisor"
            / "SKILL.md"
        )
        text = skill_md.read_text(encoding="utf-8")
        match = re.search(r"^allowed-tools:\s*(.+)$", text, re.MULTILINE)
        assert match, "Advisor SKILL.md must declare an `allowed-tools` frontmatter line"
        listed = set(match.group(1).strip().split())
        for tool_name in TestAdvisorToolNames.EXPECTED.values():
            assert tool_name in listed, (
                f"Advisor SKILL.md `allowed-tools` is missing {tool_name!r}; "
                f"found {sorted(listed)}. Keep in sync with the supported plugins."
            )
