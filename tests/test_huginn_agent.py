from __future__ import annotations

import unittest

from huginn.agent import parse_orchestrator_output


class AgentParseTests(unittest.TestCase):
    def test_parse_done_json(self) -> None:
        parsed = parse_orchestrator_output('{"action":"done","answer":"ok"}')
        self.assertEqual(parsed.action, "done")
        self.assertEqual(parsed.answer, "ok")

    def test_parse_single_tool_json(self) -> None:
        parsed = parse_orchestrator_output(
            '{"action":"tool","tool":"web_search","args":{"query":"ia"}}'
        )
        self.assertEqual(parsed.action, "tool")
        self.assertIsNotNone(parsed.tool_calls)
        self.assertEqual(parsed.tool_calls[0].tool, "web_search")
        self.assertEqual(parsed.tool_calls[0].args["query"], "ia")

    def test_parse_non_json_falls_back_to_done(self) -> None:
        parsed = parse_orchestrator_output("Resposta final em texto livre")
        self.assertEqual(parsed.action, "done")
        self.assertIn("texto livre", parsed.answer)


if __name__ == "__main__":
    unittest.main()
