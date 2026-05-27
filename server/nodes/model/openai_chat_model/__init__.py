from typing import Literal, Optional

from pydantic import Field

from .._base import ChatModelBase, ChatModelParams

from .._credentials import OpenAICredential


class OpenAIChatModelParams(ChatModelParams):
    frequency_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        json_schema_extra={"numberStepSize": 0.1},
    )
    presence_penalty: Optional[float] = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        json_schema_extra={"numberStepSize": 0.1},
    )
    response_format: Optional[Literal["text", "json_object"]] = Field(default="text")
    thinking_enabled: bool = Field(default=False)
    reasoning_effort: Optional[Literal["minimal", "low", "medium", "high"]] = Field(
        default="medium",
        json_schema_extra={"displayOptions": {"show": {"thinking_enabled": [True]}}},
    )


class OpenAIChatModelNode(ChatModelBase):
    type = "openaiChatModel"
    display_name = "OpenAI"
    subtitle = "Chat Model"
    group = ("model", "tool")
    description = "OpenAI GPT models for chat completion and generation"

    usable_as_tool = True
    tool_name = "openai_chat_model"
    tool_description = (
        "Consult OpenAI GPT as an advisor — a stronger model the operator wired in to guide "
        "your reasoning. Call AT THE START of any complex task to plan your approach, WHEN "
        "STUCK (errors recurring, approach not converging), and BEFORE DECLARING DONE to "
        "sanity-check completeness. Pose ONE focused question in `prompt` — include the context "
        "the advisor needs (the advisor cannot see your conversation). Do NOT set `model`, "
        "`api_key`, `temperature`, or other fields; the operator configured them. Returns brief "
        "tactical guidance — you do the work."
    )

    credentials = (OpenAICredential,)
    Params = OpenAIChatModelParams
