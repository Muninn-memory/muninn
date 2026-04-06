from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import OpenAI

from huginn.providers.base import LLMProvider, LLMResponse, TokenUsage

logger = logging.getLogger("huginn.providers")


class DeepSeekProvider(LLMProvider):
    def __init__(self, *, api_key: str, model: str, base_url: str, role: str) -> None:
        super().__init__(role=role, model=model)
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def _complete_sync(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        payload_messages = [{"role": "system", "content": system_prompt}]
        payload_messages.extend(messages)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=payload_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = ""
        if response.choices and response.choices[0].message.content:
            text = (response.choices[0].message.content or "").strip()

        usage_data: Any = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage_data, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_data, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage_data, "total_tokens", 0) or 0)
        if not total_tokens:
            total_tokens = prompt_tokens + completion_tokens

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=self.model,
            provider="deepseek",
        )
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
            "deepseek",
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
            logger.exception("LLM error provider=%s model=%s", "deepseek", self.model)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "LLM ok provider=%s model=%s in=%d out=%d elapsed=%.1fms",
            "deepseek",
            self.model,
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            elapsed_ms,
        )
        return response
