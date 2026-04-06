from __future__ import annotations

import json
from typing import Any

from muninn_bridge import call_muninn

DEFAULT_MEMORY_LIMIT = 10


def _parse_json_or_raw(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def recall_memory(*, query: str = "", limit: int = DEFAULT_MEMORY_LIMIT) -> str:
    if query.strip():
        return await search_memory(query=query, limit=limit)
    return await call_muninn("get_memories", {"limit": max(1, int(limit))})


async def search_memory(*, query: str, limit: int = DEFAULT_MEMORY_LIMIT) -> str:
    return await call_muninn(
        "search_memories",
        {"query": (query or "").strip(), "limit": max(1, int(limit))},
    )


async def save_memory(
    *,
    title: str,
    content: str,
    tags: list[str] | None = None,
    memory_type: str = "result",
) -> str:
    return await call_muninn(
        "save_memory",
        {
            "type": memory_type,
            "title": (title or "").strip() or "Registro Huginn",
            "content": (content or "").strip(),
            "tags": tags or [],
        },
    )
