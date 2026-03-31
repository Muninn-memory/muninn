import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from mcp_client import (
    McpClientProcessError,
    McpClientTimeoutError,
    McpProcessConfig,
    call_mcp_tool_subprocess,
)


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.eof_written = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def write_eof(self) -> None:
        self.eof_written = True


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int | None = 0,
        communicate_results: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        self.stdin = _FakeStdin()
        self.returncode = returncode
        self._communicate_results = list(communicate_results or [(b"", b"")])
        self.kill_called = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._communicate_results:
            return self._communicate_results.pop(0)
        return (b"", b"")

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9


class McpClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = McpProcessConfig(
            python_path="python",
            server_path="mcp_server.py",
            client_name="tests",
            timeout_seconds=0.1,
        )

    async def test_returns_text_for_valid_mcp_response(self) -> None:
        stdout = (
            b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}\n'
        )
        proc = _FakeProcess(returncode=0, communicate_results=[(stdout, b"")])

        with patch("mcp_client.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            text = await call_mcp_tool_subprocess(
                "get_memories",
                {"limit": 5},
                config=self.config,
            )

        self.assertEqual(text, "ok")
        self.assertTrue(proc.stdin.eof_written)
        self.assertEqual(len(proc.stdin.writes), 3)

    async def test_ignores_malformed_json_lines_when_valid_result_exists(self) -> None:
        stdout = (
            b"this-is-not-json\n"
            b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"valid"}]}}\n'
        )
        proc = _FakeProcess(returncode=0, communicate_results=[(stdout, b"")])

        with patch("mcp_client.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            text = await call_mcp_tool_subprocess(
                "get_memories",
                {"limit": 5},
                config=self.config,
            )

        self.assertEqual(text, "valid")

    async def test_timeout_kills_process_and_raises_timeout_error(self) -> None:
        proc = _FakeProcess(returncode=None, communicate_results=[(b"", b"")])

        async def _raise_timeout(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        with (
            patch("mcp_client.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
            patch("mcp_client.asyncio.wait_for", new=AsyncMock(side_effect=_raise_timeout)),
        ):
            with self.assertRaises(McpClientTimeoutError):
                await call_mcp_tool_subprocess(
                    "get_memories",
                    {"limit": 5},
                    config=self.config,
                )

        self.assertTrue(proc.kill_called)

    async def test_non_zero_exit_without_result_raises_process_error(self) -> None:
        proc = _FakeProcess(
            returncode=2,
            communicate_results=[(b'{"jsonrpc":"2.0","id":0}\n', b"boom")],
        )

        with patch("mcp_client.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            with self.assertRaises(McpClientProcessError):
                await call_mcp_tool_subprocess(
                    "get_memories",
                    {"limit": 5},
                    config=self.config,
                )


if __name__ == "__main__":
    unittest.main()
