from __future__ import annotations

import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from huginn.agent import AgentLoop
from huginn.channels.base import HuginnMessage
from huginn.channels.telegram import TelegramChannel
from huginn.providers.base import LLMProvider, LLMResponse, TokenUsage
from huginn.providers.claude import ClaudeProvider
from huginn.providers.deepseek import DeepSeekProvider
from huginn.tools import registry
from huginn.tools.registry import ToolRuntimeContext, ToolSpec, execute_tool


class _StubSessionLogger:
    def __init__(self) -> None:
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def add_usage(self, *, phase: str, usage: TokenUsage, note: str = "") -> None:
        _ = (phase, usage, note)
        self.total_tokens += int(usage.total_tokens or 0)

    def add_event(self, *, phase: str, note: str) -> None:
        _ = (phase, note)


class _DoneProvider:
    async def complete(self, **_kwargs) -> LLMResponse:
        return LLMResponse(
            text='{"action":"done","answer":"ok"}',
            usage=TokenUsage(
                prompt_tokens=5,
                completion_tokens=2,
                total_tokens=7,
                provider="test",
                model="test-model",
            ),
        )


class AgentLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_logs_start_done_and_finish(self) -> None:
        settings = SimpleNamespace(
            huginn_mode="claude_orchestrator",
            llm_boost_enabled=False,
            llm_validate_enabled=False,
            max_iterations=3,
            max_subagents=1,
            subagent_max_iter=1,
        )
        with patch("huginn.agent.get_settings", return_value=settings), patch(
            "huginn.agent.get_provider", return_value=_DoneProvider()
        ):
            with self.assertLogs("huginn.agent", level="INFO") as logs:
                result = await AgentLoop(
                    session_id="sid-agent",
                    channel="internal",
                    session_logger=_StubSessionLogger(),
                ).run("ping")

        self.assertEqual(result, "ok")
        self.assertTrue(any("[sid-agent] START" in line for line in logs.output))
        self.assertTrue(any("[sid-agent] DONE" in line for line in logs.output))
        self.assertTrue(any("[sid-agent] FINISH" in line for line in logs.output))


class ToolLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_tool_logs_success_and_preserves_dict_contract(self) -> None:
        async def _ok_handler(args: dict[str, object], _context: ToolRuntimeContext) -> str:
            return f"ok:{args.get('value')}"

        spec = ToolSpec(
            name="unit_ok",
            description="test",
            schema={"type": "object", "required": ["value"]},
            handler=_ok_handler,
        )
        with patch.dict(registry.TOOLS, {"unit_ok": spec}, clear=False):
            with self.assertLogs("huginn.tools", level="INFO") as logs:
                result = await execute_tool(
                    "unit_ok",
                    {"value": "x"},
                    context=ToolRuntimeContext(session_id="sid-tool", channel="internal"),
                )

        self.assertIsInstance(result, dict)
        self.assertTrue(result["ok"])
        self.assertTrue(any("TOOL execute session_id=sid-tool" in line for line in logs.output))
        self.assertTrue(any("TOOL ok session_id=sid-tool" in line for line in logs.output))

    async def test_execute_tool_logs_error_and_returns_tool_error_dict(self) -> None:
        async def _err_handler(_args: dict[str, object], _context: ToolRuntimeContext) -> str:
            raise RuntimeError("boom")

        spec = ToolSpec(
            name="unit_err",
            description="test",
            schema={"type": "object"},
            handler=_err_handler,
        )
        with patch.dict(registry.TOOLS, {"unit_err": spec}, clear=False):
            with self.assertLogs("huginn.tools", level="ERROR") as logs:
                result = await execute_tool(
                    "unit_err",
                    {},
                    context=ToolRuntimeContext(session_id="sid-tool", channel="internal"),
                )

        self.assertIsInstance(result, dict)
        self.assertFalse(result["ok"])
        self.assertIn("[tool_error] unit_err falhou", result["error"])
        self.assertTrue(any("TOOL error session_id=sid-tool" in line for line in logs.output))


class ProviderLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_provider_logs_call_and_success(self) -> None:
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))],
            usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )
        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        LLMProvider.__init__(provider, role="exec", model="deepseek-test")
        provider._client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **_kwargs: response)
            )
        )

        with self.assertLogs("huginn.providers", level="INFO") as logs:
            out = await provider.complete(
                system_prompt="system",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertEqual(out.text, "ok")
        self.assertTrue(any("LLM call provider=deepseek model=deepseek-test" in line for line in logs.output))
        self.assertTrue(any("LLM ok provider=deepseek model=deepseek-test in=11 out=7" in line for line in logs.output))

    async def test_claude_provider_logs_call_and_success(self) -> None:
        response = types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="ok from claude")],
            usage=types.SimpleNamespace(input_tokens=13, output_tokens=9),
        )
        provider = ClaudeProvider.__new__(ClaudeProvider)
        LLMProvider.__init__(provider, role="orchestrator", model="claude-test")
        provider._client = types.SimpleNamespace(
            messages=types.SimpleNamespace(create=lambda **_kwargs: response)
        )

        with self.assertLogs("huginn.providers", level="INFO") as logs:
            out = await provider.complete(
                system_prompt="system",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertEqual(out.text, "ok from claude")
        self.assertTrue(any("LLM call provider=anthropic model=claude-test" in line for line in logs.output))
        self.assertTrue(any("LLM ok provider=anthropic model=claude-test in=13 out=9" in line for line in logs.output))


class ChannelLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_channel_logs_recv_and_send(self) -> None:
        settings = SimpleNamespace(
            telegram_bot_token="",
            telegram_allowed_chat_id=0,
            huginn_auth_keyword="wodan",
        )

        async def _runner(_task: str, _session_id: str, _channel: str) -> str:
            return "ok"

        sent: list[str] = []

        async def _reply(text: str) -> None:
            sent.append(text)

        channel = TelegramChannel(agent_runner=_runner, settings=settings)
        message = HuginnMessage(
            channel="telegram",
            sender="123",
            text="/start",
            session_id="telegram-123",
        )
        with self.assertLogs("huginn.channels", level="INFO") as logs:
            result = await channel.process_message(message, reply_func=_reply)

        self.assertIn("Huginn ativo", result)
        self.assertGreater(len(sent), 0)
        self.assertTrue(any("RECV channel=telegram sender=123" in line for line in logs.output))
        self.assertTrue(any("SEND channel=telegram recipient=123" in line for line in logs.output))

    async def test_telegram_channel_logs_send_error(self) -> None:
        settings = SimpleNamespace(
            telegram_bot_token="",
            telegram_allowed_chat_id=0,
            huginn_auth_keyword="wodan",
        )

        async def _runner(_task: str, _session_id: str, _channel: str) -> str:
            return "ok"

        async def _failing_reply(_text: str) -> None:
            raise RuntimeError("send failed")

        channel = TelegramChannel(agent_runner=_runner, settings=settings)
        message = HuginnMessage(
            channel="telegram",
            sender="123",
            text="/start",
            session_id="telegram-123",
        )

        with self.assertLogs("huginn.channels", level="ERROR") as logs:
            with self.assertRaises(RuntimeError):
                await channel.process_message(message, reply_func=_failing_reply)

        self.assertTrue(any("SEND error channel=telegram recipient=123" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
