from __future__ import annotations

# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import os
import sys

MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "mcp_server.py")
PYTHON_PATH = sys.executable

logger = logging.getLogger(__name__)


async def call_muninn(tool_name: str, arguments: dict[str, object]) -> str:
    """Chama uma ferramenta do MCP server do Muninn."""
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )
    proc = await asyncio.create_subprocess_exec(
        PYTHON_PATH,
        MCP_SERVER_PATH,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "huginn-bridge", "version": "1.0"},
            },
        }
    )
    assert proc.stdin is not None
    proc.stdin.write((init + "\n").encode())
    proc.stdin.write(
        (
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
            + "\n"
        ).encode()
    )
    proc.stdin.write((payload + "\n").encode())
    proc.stdin.write_eof()

    stdout, stderr = await proc.communicate()

    if stderr and logger.isEnabledFor(logging.DEBUG):
        logger.debug("Muninn stderr: %s", stderr.decode(errors="ignore"))

    for line in stdout.decode().splitlines():
        try:
            data = json.loads(line)
            if data.get("id") == 1:
                contents = data.get("result", {}).get("content", [])
                return contents[0].get("text", "") if contents else ""
        except Exception as exc:  # noqa: BLE001
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Falha ao parsear linha de saída do Muninn: %r (%r)",
                    line,
                    exc,
                )
            continue

    if proc.returncode not in (0, None) and logger.isEnabledFor(logging.DEBUG):
        logger.debug("Muninn finalizou com código de saída %s", proc.returncode)

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