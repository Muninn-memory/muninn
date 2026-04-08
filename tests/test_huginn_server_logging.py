from __future__ import annotations

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - dependency guard
    TestClient = None

if TestClient is not None:
    import huginn.server as server


def _settings_stub(**overrides):
    base = {
        "huginn_mode": "claude_orchestrator",
        "llm_boost_enabled": False,
        "llm_validate_enabled": False,
        "browser_tools_enabled": False,
        "browser_headless": True,
        "whatsapp_enabled": False,
        "instagram_enabled": False,
        "max_iterations": 30,
        "max_subagents": 3,
        "subagent_max_iter": 8,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@unittest.skipIf(TestClient is None, "fastapi nao instalado")
class HuginnServerLoggingTests(unittest.TestCase):
    def test_status_route_logs_request_and_response(self) -> None:
        with patch("huginn.server.get_settings", return_value=_settings_stub()):
            with TestClient(server.app) as client, self.assertLogs("huginn.server", level="INFO") as logs:
                response = client.get("/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("-> GET /status" in line for line in logs.output))
        self.assertTrue(any("<- GET /status | status=200" in line for line in logs.output))

    def test_task_route_logs_session_and_channel(self) -> None:
        async def fake_arun(_task: str, *, session_id: str, channel: str) -> str:
            _ = (session_id, channel)
            return "done"

        with patch("huginn.server.arun", side_effect=fake_arun), patch(
            "huginn.server.session_report", return_value={"entries": [], "totals": {}}
        ), patch("huginn.server.get_settings", return_value=_settings_stub()):
            with TestClient(server.app) as client, self.assertLogs(
                "huginn.server", level="INFO"
            ) as logs:
                response = client.post("/task", json={"task": "hello", "channel": "internal"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("TASK start channel=internal" in line for line in logs.output))
        self.assertTrue(any("TASK done channel=internal" in line for line in logs.output))

    def test_middleware_logs_unhandled_exceptions(self) -> None:
        path = f"/_boom_{uuid.uuid4().hex}"

        async def boom() -> None:
            await asyncio.sleep(0)
            raise RuntimeError("boom")

        server.app.add_api_route(path, boom, methods=["GET"])

        with patch("huginn.server.get_settings", return_value=_settings_stub()):
            with TestClient(server.app, raise_server_exceptions=False) as client, self.assertLogs(
                "huginn.server", level="ERROR"
            ) as logs:
                response = client.get(path)

        self.assertEqual(response.status_code, 500)
        self.assertTrue(any("UNHANDLED exception in request" in line for line in logs.output))

    def test_startup_fails_when_browser_preflight_fails(self) -> None:
        settings = _settings_stub(browser_tools_enabled=True, browser_headless=True)
        with patch("huginn.server.get_settings", return_value=settings), patch(
            "huginn.server.preflight_browser_runtime",
            side_effect=RuntimeError("Browser runtime indisponivel"),
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(server.startup_event())


if __name__ == "__main__":
    unittest.main()
