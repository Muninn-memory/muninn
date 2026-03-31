import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import muninn
from mcp_client import McpClientProcessError


class MuninnTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_history_invalid_json_returns_empty_and_logs(self) -> None:
        async def fake_mcp_caller(_tool: str, _arguments: dict[str, object]) -> str:
            return "not-json"

        with self.assertLogs("muninn", level="WARNING") as logs:
            history = await muninn.load_history("session-1", mcp_caller=fake_mcp_caller)

        self.assertEqual(history, [])
        self.assertTrue(any("JSON invalido" in message for message in logs.output))

    async def test_call_mcp_tool_returns_empty_on_adapter_failure(self) -> None:
        with (
            patch(
                "muninn.call_mcp_tool_subprocess",
                new=AsyncMock(side_effect=McpClientProcessError("boom")),
            ),
            self.assertLogs("muninn", level="ERROR"),
        ):
            result = await muninn.call_mcp_tool("get_memories", {"limit": 5})

        self.assertEqual(result, "")

    async def test_extract_memory_structure_fallback_is_deterministic(self) -> None:
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))]
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response

        with patch("openai.OpenAI", return_value=fake_client):
            result = await muninn.extract_memory_structure("Lembrar de comprar cafe")

        self.assertEqual(result["type"], "note")
        self.assertEqual(result["content"], "Lembrar de comprar cafe")
        self.assertEqual(result["tags"], ["auto"])

    async def test_extract_event_details_invalid_json_returns_empty_dict(self) -> None:
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))]
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response

        with patch("openai.OpenAI", return_value=fake_client):
            result = await muninn.extract_event_details("agendar reuniao amanha as 10")

        self.assertEqual(result, {})

    async def test_memory_save_confirm_executes_real_tool_once(self) -> None:
        fake_caller = AsyncMock(return_value="Memoria salva")
        with patch(
            "muninn.extract_memory_structure",
            new=AsyncMock(
                return_value={
                    "type": "preference",
                    "title": "Cidade natal",
                    "content": "Minha cidade natal e o Rio de Janeiro",
                    "tags": ["local", "origem"],
                }
            ),
        ):
            handled, pending, reply = await muninn._route_deterministic_action(
                "salve na memoria que minha cidade natal e o Rio de Janeiro",
                mcp_caller=fake_caller,
            )

        self.assertTrue(handled)
        self.assertIsNotNone(pending)
        self.assertIn("Confirmo?", reply or "")
        self.assertEqual(fake_caller.await_count, 0)

        handled_confirm, pending_after, confirm_reply = await muninn._handle_pending_confirmation(
            pending,
            "sim",
            mcp_caller=fake_caller,
        )

        self.assertTrue(handled_confirm)
        self.assertIsNone(pending_after)
        self.assertEqual(confirm_reply, "Memoria salva")
        fake_caller.assert_awaited_once_with("save_memory", pending.arguments)

    async def test_memory_save_intent_accepts_salv_variation(self) -> None:
        fake_caller = AsyncMock(return_value="Memoria salva")
        with patch(
            "muninn.extract_memory_structure",
            new=AsyncMock(
                return_value={
                    "type": "note",
                    "title": "Cidade",
                    "content": "Minha cidade natal e o Rio",
                    "tags": ["auto"],
                }
            ),
        ):
            handled, pending, reply = await muninn._route_deterministic_action(
                "salv na memoria que minha cidade natal e o Rio",
                mcp_caller=fake_caller,
            )

        self.assertTrue(handled)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.tool_name, "save_memory")
        self.assertIn("Confirmo?", reply or "")
        self.assertEqual(fake_caller.await_count, 0)

    async def test_memory_save_cancel_does_not_execute_tool(self) -> None:
        pending = muninn.PendingAction(
            action_type="memory_save",
            tool_name="save_memory",
            arguments={"type": "note", "title": "x", "content": "y", "tags": ["auto"]},
            confirm_message='Vou registrar: "x". Confirmo?',
        )
        fake_caller = AsyncMock(return_value="nao deve chamar")

        handled, pending_after, reply = await muninn._handle_pending_confirmation(
            pending,
            "nao",
            mcp_caller=fake_caller,
        )

        self.assertTrue(handled)
        self.assertIsNone(pending_after)
        self.assertIn("cancelada", reply)
        self.assertEqual(fake_caller.await_count, 0)

    async def test_memory_search_calls_search_memories(self) -> None:
        fake_caller = AsyncMock(
            return_value='[{"title":"Cidade natal","content":"Rio de Janeiro","type":"preference","tags":["local"]}]'
        )
        handled, pending, reply = await muninn._route_deterministic_action(
            "busque na memoria cidade natal",
            mcp_caller=fake_caller,
        )

        self.assertTrue(handled)
        self.assertIsNone(pending)
        self.assertIn("Memorias encontradas", reply or "")
        fake_caller.assert_awaited_once_with(
            "search_memories",
            {"query": "cidade natal", "limit": 10},
        )

    async def test_calendar_update_creates_pending_and_confirms_update_tool(self) -> None:
        with (
            patch(
                "muninn._pick_best_calendar_event",
                return_value={"id": "evt-1", "title": "Reuniao semanal", "start": "2026-03-31T10:00:00"},
            ),
            patch(
                "muninn.extract_event_details",
                new=AsyncMock(
                    return_value={
                        "title": "Reuniao semanal",
                        "date": "2026-04-02",
                        "time": "14:30",
                        "location": "Sala 2",
                        "description": "Sprint",
                    }
                ),
            ),
        ):
            fake_caller = AsyncMock(return_value="Evento atualizado")
            handled, pending, reply = await muninn._route_deterministic_action(
                "atualize a reuniao semanal para 2026-04-02 14:30 na sala 2",
                mcp_caller=fake_caller,
            )

        self.assertTrue(handled)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.tool_name, "update_calendar_event")
        self.assertIn("google_event_id", pending.arguments)
        self.assertIn("Confirmo?", reply or "")

        handled_confirm, pending_after, confirm_reply = await muninn._handle_pending_confirmation(
            pending,
            "sim",
            mcp_caller=fake_caller,
        )
        self.assertTrue(handled_confirm)
        self.assertIsNone(pending_after)
        self.assertEqual(confirm_reply, "Evento atualizado")
        fake_caller.assert_awaited_once_with("update_calendar_event", pending.arguments)

    async def test_task_create_creates_pending_and_confirms_create_tool(self) -> None:
        with patch(
            "muninn.extract_task_details",
            new=AsyncMock(
                return_value={"title": "Pagar conta de luz", "due": "2026-04-03T12:00:00Z", "notes": "boleto"}
            ),
        ):
            fake_caller = AsyncMock(return_value="Tarefa criada")
            handled, pending, reply = await muninn._route_deterministic_action(
                "crie uma tarefa pagar conta de luz",
                mcp_caller=fake_caller,
            )

        self.assertTrue(handled)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.tool_name, "create_google_task")
        self.assertIn("Confirmo?", reply or "")

        handled_confirm, pending_after, confirm_reply = await muninn._handle_pending_confirmation(
            pending,
            "sim",
            mcp_caller=fake_caller,
        )
        self.assertTrue(handled_confirm)
        self.assertIsNone(pending_after)
        self.assertEqual(confirm_reply, "Tarefa criada")
        fake_caller.assert_awaited_once_with("create_google_task", pending.arguments)

    async def test_chat_loop_skips_deepseek_when_deterministic_action_is_handled(self) -> None:
        called_tools: list[str] = []

        async def fake_mcp_caller(tool: str, _arguments: dict[str, object]) -> str:
            called_tools.append(tool)
            if tool == "get_conversation":
                return "[]"
            if tool == "save_memory":
                return "Memoria salva com sucesso."
            if tool == "save_conversation":
                return "ok"
            if tool == "get_memories":
                return "[]"
            return ""

        with (
            patch("muninn.Prompt.ask", side_effect=["salve na memoria que minha cidade natal e o Rio", "sim", "sair"]),
            patch(
                "muninn.extract_memory_structure",
                new=AsyncMock(
                    return_value={
                        "type": "preference",
                        "title": "Cidade natal",
                        "content": "Minha cidade natal e o Rio",
                        "tags": ["local"],
                    }
                ),
            ),
            patch("muninn.chat_deepseek", new=AsyncMock()) as mock_chat_deepseek,
        ):
            await muninn.chat_loop("deepseek", "session-x", mcp_caller=fake_mcp_caller)

        self.assertEqual(mock_chat_deepseek.await_count, 0)
        self.assertIn("save_memory", called_tools)

    async def test_chat_loop_calls_deepseek_when_no_deterministic_action(self) -> None:
        async def fake_mcp_caller(tool: str, _arguments: dict[str, object]) -> str:
            if tool == "get_conversation":
                return "[]"
            if tool == "get_memories":
                return "[]"
            if tool == "save_conversation":
                return "ok"
            return ""

        with (
            patch("muninn.Prompt.ask", side_effect=["qual a capital da franca?", "sair"]),
            patch(
                "muninn.chat_deepseek",
                new=AsyncMock(
                    return_value={
                        "text": "Paris.",
                        "reasoning": None,
                        "tool_calls": [],
                        "stop_reason": "end_turn",
                    }
                ),
            ) as mock_chat_deepseek,
        ):
            await muninn.chat_loop("deepseek", "session-y", mcp_caller=fake_mcp_caller)

        self.assertEqual(mock_chat_deepseek.await_count, 1)

    def test_tools_schema_contains_calendar_and_task_tools(self) -> None:
        names = {tool["name"] for tool in muninn.TOOLS_SCHEMA}
        required = {
            "create_calendar_event",
            "list_calendar_events",
            "delete_calendar_event",
            "update_calendar_event",
            "create_google_task",
            "list_google_tasks",
        }
        self.assertTrue(required.issubset(names))


if __name__ == "__main__":
    unittest.main()
