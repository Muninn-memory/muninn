import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import google_tools


class GoogleToolsTests(unittest.TestCase):
    @patch("google_tools.get_calendar_service")
    def test_delete_event_calls_google_calendar(self, mock_get_calendar_service: MagicMock) -> None:
        service = MagicMock()
        mock_get_calendar_service.return_value = service

        result = google_tools.delete_event("evt-123")

        self.assertTrue(result)
        service.events.return_value.delete.assert_called_once_with(
            calendarId=google_tools.MUNINN_EMAIL,
            eventId="evt-123",
        )
        service.events.return_value.delete.return_value.execute.assert_called_once()

    def test_google_tools_has_single_delete_event_definition(self) -> None:
        source = Path(google_tools.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function_names = [
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        ]
        self.assertEqual(function_names.count("delete_event"), 1)


if __name__ == "__main__":
    unittest.main()
