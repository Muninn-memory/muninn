from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderConfigError(RuntimeError):
    """Provider configuration is invalid or incomplete."""


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    provider: str = ""
    cost_usd: float = 0.0


@dataclass(slots=True)
class LLMResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: Any | None = None


class LLMProvider(ABC):
    def __init__(self, *, role: str, model: str) -> None:
        self.role = role
        self.model = model

    @abstractmethod
    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        raise NotImplementedError
