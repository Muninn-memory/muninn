from __future__ import annotations

# -*- coding: utf-8 -*-
import logging
import os
import sys

from mcp_client import (
    McpClientError,
    McpProcessConfig,
    call_mcp_tool_subprocess,
)

MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mcp_server.py")
PYTHON_PATH = sys.executable

logger = logging.getLogger(__name__)
MCP_CONFIG = McpProcessConfig(
    python_path=PYTHON_PATH,
    server_path=MCP_SERVER_PATH,
    client_name="huginn-bridge",
    timeout_seconds=15.0,
)


async def call_muninn(tool_name: str, arguments: dict[str, object]) -> str:
    """Chama uma ferramenta do MCP server do Muninn."""
    try:
        return await call_mcp_tool_subprocess(
            tool_name,
            arguments,
            config=MCP_CONFIG,
            logger=logger,
        )
    except McpClientError:
        logger.exception("Falha ao chamar MCP tool=%s", tool_name)
        return ""


async def save_to_memory(title: str, content: str, tags: list[str]) -> str:
    """Salva informação na memória do Muninn."""
    return await call_muninn(
        "save_memory",
        {
            "type": "result",
            "title": title,
            "content": content,
            "tags": tags,
        },
    )


async def get_memories(limit: int = 20) -> str:
    """Recupera memórias do Muninn."""
    return await call_muninn("get_memories", {"limit": limit})
