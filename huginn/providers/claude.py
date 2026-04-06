from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from huginn.providers.base import LLMProvider, LLMResponse, TokenUsage

logger = logging.getLogger("huginn.providers")


class ClaudeProvider(LLMProvider):
    def __init__(self, *, api_key: str, model: str, role: str) -> None:
        super().__init__(role=role, model=model)
        try:
            from anthropic import Anthropic
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("Pacote 'anthropic' nao disponivel para ClaudeProvider") from exc

        self._client = Anthropic(api_key=api_key)

    def _complete_sync(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        payload_messages: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "tool":
                role = "user"
                content = f"[tool_result]\n{content}"
            payload_messages.append({"role": role, "content": content})

        response = self._client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=payload_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text_parts.append(getattr(block, "text", "") or "")
        text = "\n".join(part for part in text_parts if part.strip()).strip()

        usage = TokenUsage(
            prompt_tokens=int(getattr(getattr(response, "usage", None), "input_tokens", 0) or 0),
            completion_tokens=int(
                getattr(getattr(response, "usage", None), "output_tokens", 0) or 0
            ),
            model=self.model,
            provider="anthropic",
        )
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        return LLMResponse(text=text, usage=usage, raw=response)

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> LLMResponse:
        logger.info(
            "LLM call provider=%s model=%s messages=%d",
            "anthropic",
            self.model,
            len(messages),
        )
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                self._complete_sync,
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception:
            logger.exception("LLM error provider=%s model=%s", "anthropic", self.model)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "LLM ok provider=%s model=%s in=%d out=%d elapsed=%.1fms",
            "anthropic",
            self.model,
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            elapsed_ms,
        )
        return response
