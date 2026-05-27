from typing import Optional

from pydantic import Field

from .._base import ChatModelBase, ChatModelParams

from .._credentials import AnthropicCredential


class AnthropicChatModelParams(ChatModelParams):
    top_k: Optional[int] = Field(default=40, ge=1, le=100)
    thinking_enabled: bool = Field(default=False)
    thinking_budget: Optional[int] = Field(
        default=2048,
        ge=1024,
        le=16000,
        json_schema_extra={"displayOptions": {"show": {"thinking_enabled": [True]}}},
    )


class AnthropicChatModelNode(ChatModelBase):
    type = "anthropicChatModel"
    display_name = "Claude"
    subtitle = "Chat Model"
    group = ("model", "tool")
    description = "Anthropic Claude models for conversation and analysis"

    usable_as_tool = True
    tool_name = "anthropic_chat_model"
    tool_description = (
        "Consult Anthropic Claude as an advisor — a stronger model the operator wired in "
        "to guide your reasoning. Call AT THE START of any complex task to plan your approach, "
        "WHEN STUCK (errors recurring, approach not converging), and BEFORE DECLARING DONE to "
        "sanity-check completeness. Pose ONE focused question in `prompt` — include the context "
        "the advisor needs (the advisor cannot see your conversation). Do NOT set `model`, "
        "`api_key`, `temperature`, or other fields; the operator configured them. Returns brief "
        "tactical guidance — you do the work."
    )

    credentials = (AnthropicCredential,)
    Params = AnthropicChatModelParams
