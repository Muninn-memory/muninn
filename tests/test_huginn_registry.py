from __future__ import annotations

import unittest

from huginn.tools.registry import ToolRuntimeContext, execute_tool


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tool_returns_error(self) -> None:
        result = await execute_tool(
            "nao_existe",
            {},
            context=ToolRuntimeContext(session_id="s1", channel="tests"),
        )
        self.assertFalse(result["ok"])
        self.assertIn("desconhecida", result["error"])

    async def test_required_field_validation(self) -> None:
        result = await execute_tool(
            "web_search",
            {},
            context=ToolRuntimeContext(session_id="s1", channel="tests"),
        )
        self.assertFalse(result["ok"])
        self.assertIn("campo obrigatorio ausente", result["error"])

    async def test_spawn_subagent_stub_without_handler(self) -> None:
        result = await execute_tool(
            "spawn_subagent",
            {"task": "quebre em subtarefas"},
            context=ToolRuntimeContext(session_id="s1", channel="tests"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "subagents not yet implemented")


if __name__ == "__main__":
    unittest.main()
