from __future__ import annotations

import logging
import runpy
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cli


class HuginnEntrypointTests(unittest.TestCase):
    def test_cli_huginn_server_uses_log_config_none(self) -> None:
        fake_settings = SimpleNamespace(
            huginn_host="0.0.0.0",
            huginn_port=8000,
            log_dir="./logs",
        )
        fake_uvicorn = SimpleNamespace(run=MagicMock())

        with patch.object(cli, "get_settings", return_value=fake_settings), patch.object(
            cli, "configure_logging"
        ) as configure_mock, patch.dict(sys.modules, {"uvicorn": fake_uvicorn}):
            cli.huginn_server(host="", port=0)

        configure_mock.assert_called_once_with("./logs")
        fake_uvicorn.run.assert_called_once()
        kwargs = fake_uvicorn.run.call_args.kwargs
        self.assertEqual(kwargs["host"], "0.0.0.0")
        self.assertEqual(kwargs["port"], 8000)
        self.assertEqual(kwargs["log_config"], None)

    def test_huginn_py_configures_logging_before_main(self) -> None:
        order: list[str] = []
        root = logging.getLogger()
        added_handler: logging.Handler | None = None
        handler_count_at_main = {"value": 0}

        fake_huginn = types.ModuleType("huginn")
        fake_channels = types.ModuleType("huginn.channels")
        fake_telegram = types.ModuleType("huginn.channels.telegram")

        def fake_configure_logging() -> None:
            nonlocal added_handler
            order.append("configure")
            if added_handler is None:
                added_handler = logging.NullHandler()
                root.addHandler(added_handler)

        def fake_main() -> None:
            order.append("main")
            handler_count_at_main["value"] = len(root.handlers)

        fake_huginn.configure_logging = fake_configure_logging  # type: ignore[attr-defined]
        fake_telegram.main = fake_main  # type: ignore[attr-defined]

        script_path = Path(__file__).resolve().parents[1] / "huginn.py"
        with patch.dict(
            sys.modules,
            {
                "huginn": fake_huginn,
                "huginn.channels": fake_channels,
                "huginn.channels.telegram": fake_telegram,
            },
            clear=False,
        ):
            runpy.run_path(str(script_path), run_name="__main__")

        self.assertEqual(order, ["configure", "main"])
        self.assertGreater(handler_count_at_main["value"], 0)

        if added_handler is not None:
            root.removeHandler(added_handler)


if __name__ == "__main__":
    unittest.main()
