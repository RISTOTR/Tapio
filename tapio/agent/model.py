"""Small vendor-neutral model protocol; no provider SDK leaks into the coordinator."""

from typing import Literal, Protocol

from pydantic import Field

from tapio.tools.schemas import Schema


class ToolCall(Schema):
    name: str = Field(min_length=1, max_length=100)
    arguments: dict


class ResultReference(Schema):
    call_index: int = Field(ge=0, strict=True)
    # References select an entire typed result. They cannot insert or recompute values.


MessageKey = Literal[
    "results", "missing_evidence", "unsupported", "human_review", "tax_review_required"
]


class ModelTurn(Schema):
    call: ToolCall | None = None
    references: list[ResultReference] = Field(default_factory=list, max_length=8)
    message_key: MessageKey = "results"


class AgentModel(Protocol):
    async def generate_with_tools(self, messages: list[dict], tools: list[dict]) -> ModelTurn: ...


class CallableModel:
    """Inject one chosen provider's async request converter, isolated from orchestration."""

    def __init__(self, generate):
        self.generate = generate

    async def generate_with_tools(self, messages, tools):
        return ModelTurn.model_validate(await self.generate(messages, tools))
