from __future__ import annotations

from huginn.providers.factory import get_provider

DEEP_THINK_SYSTEM = (
    "Voce e um agente de raciocinio profundo. Responda com analise objetiva, estruturada e verificavel."
)


async def deep_think(*, question: str) -> str:
    provider = get_provider("reasoner")
    response = await provider.complete(
        system_prompt=DEEP_THINK_SYSTEM,
        messages=[{"role": "user", "content": (question or "").strip()}],
        max_tokens=2048,
        temperature=0.1,
    )
    return response.text.strip()
