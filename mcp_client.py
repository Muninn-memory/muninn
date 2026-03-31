from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any


class McpClientError(Exception):
    """Base class for MCP client failures."""


class McpClientTimeoutError(McpClientError):
    """Raised when an MCP subprocess call times out."""


class McpClientProtocolError(McpClientError):
    """Raised when MCP response data is malformed or incomplete."""


class McpClientProcessError(McpClientError):
    """Raised when the subprocess exits with an error before returning a result."""


@dataclass(slots=True)
class McpProcessConfig:
    python_path: str
    server_path: str
    client_name: str
    timeout_seconds: float = 15.0


def _parse_tool_text_from_stdout(stdout_text: str, logger: logging.Logger) -> str | None:
    for line in stdout_text.splitlines():
        if not line.strip():
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON MCP stdout line: %r", line)
            continue

        if not isinstance(data, dict) or data.get("id") != 1:
            continue

        result = data.get("result")
        if not isinstance(result, dict):
            raise McpClientProtocolError("MCP response missing valid 'result' object")

        content = result.get("content")
        if content is None:
            return ""
        if not isinstance(content, list):
            raise McpClientProtocolError("MCP response 'content' must be a list")
        if not content:
            return ""

        first_item = content[0]
        if not isinstance(first_item, dict):
            raise McpClientProtocolError("MCP response 'content[0]' must be an object")

        text = first_item.get("text", "")
        if text is None:
            return ""
        if not isinstance(text, str):
            raise McpClientProtocolError("MCP response 'text' must be a string")
        return text

    return None


async def call_mcp_tool_subprocess(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    config: McpProcessConfig,
    logger: logging.Logger | None = None,
) -> str:
    active_logger = logger or logging.getLogger(__name__)

    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": config.client_name, "version": "1.0"},
            },
        }
    )

    proc = await asyncio.create_subprocess_exec(
        config.python_path,
        config.server_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    if proc.stdin is None:
        raise McpClientProcessError("MCP subprocess stdin is unavailable")

    proc.stdin.write((init + "\n").encode())
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode())
    proc.stdin.write((payload + "\n").encode())
    proc.stdin.write_eof()

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=config.timeout_seconds)
    except asyncio.TimeoutError as exc:
        if proc.returncode is None:
            proc.kill()
            await proc.communicate()
        raise McpClientTimeoutError(
            f"MCP call timed out after {config.timeout_seconds:.1f}s for tool '{tool_name}'"
        ) from exc

    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace").strip()

    result_text = _parse_tool_text_from_stdout(stdout_text, active_logger)
    if result_text is not None:
        if proc.returncode not in (0, None):
            active_logger.warning(
                "MCP subprocess exited with non-zero code after response",
                extra={"tool_name": tool_name, "return_code": proc.returncode},
            )
        return result_text

    if proc.returncode not in (0, None):
        raise McpClientProcessError(
            f"MCP subprocess failed for tool '{tool_name}' with return code {proc.returncode}. "
            f"stderr={stderr_text or '(empty)'}"
        )

    raise McpClientProtocolError(
        f"MCP response for tool '{tool_name}' did not include a valid tool result"
    )
