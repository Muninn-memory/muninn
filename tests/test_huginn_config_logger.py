from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from huginn.config import get_settings, reload_settings
from huginn.logger import SessionLogger
from huginn.logging_config import configure_logging, get_managed_handler_count
from huginn.providers.base import TokenUsage


class ConfigAndLoggerTests(unittest.TestCase):
    def tearDown(self) -> None:
        reload_settings()

    def test_invalid_mode_raises(self) -> None:
        with patch.dict(os.environ, {"HUGINN_MODE": "invalid_mode"}, clear=False):
            with self.assertRaises(ValueError):
                reload_settings()

    def test_settings_expose_huginn_host_and_port(self) -> None:
        settings = get_settings()
        self.assertIsInstance(settings.huginn_host, str)
        self.assertIsInstance(settings.huginn_port, int)
        self.assertGreater(settings.huginn_port, 0)

    def test_configure_logging_is_idempotent(self) -> None:
        tmp_dir = Path("tests") / f"_tmp_huginn_runtime_{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(str(tmp_dir))
        first_count = get_managed_handler_count()
        configure_logging(str(tmp_dir))
        second_count = get_managed_handler_count()
        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 2)
        configure_logging("./logs")

    def test_server_import_does_not_duplicate_managed_handlers(self) -> None:
        if importlib.util.find_spec("fastapi") is None:
            self.skipTest("fastapi nao instalado")
        tmp_dir = Path("tests") / f"_tmp_huginn_runtime_{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, {"LOG_DIR": str(tmp_dir)}, clear=False):
            reload_settings()
            configure_logging(str(tmp_dir))
            first_count = get_managed_handler_count()
            import huginn.server as huginn_server

            importlib.reload(huginn_server)
            second_count = get_managed_handler_count()
            self.assertEqual(first_count, 2)
            self.assertEqual(second_count, 2)
            configure_logging("./logs")

    def test_configure_logging_sets_noise_loggers_to_warning(self) -> None:
        tmp_dir = Path("tests") / f"_tmp_huginn_runtime_{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(str(tmp_dir))
        self.assertEqual(logging.getLogger("httpx").level, logging.WARNING)
        self.assertEqual(logging.getLogger("primp").level, logging.WARNING)
        self.assertEqual(logging.getLogger("ddgs.ddgs").level, logging.ERROR)
        self.assertEqual(logging.getLogger("uvicorn.access").level, logging.WARNING)
        configure_logging("./logs")

    def test_configure_logging_sets_pythonutf8_env_and_handler_errors_replace(self) -> None:
        tmp_dir = Path("tests") / f"_tmp_huginn_runtime_{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, {"PYTHONUTF8": "0"}, clear=False):
            configure_logging(str(tmp_dir))
            self.assertEqual(os.environ.get("PYTHONUTF8"), "0")

        configure_logging(str(tmp_dir))
        file_handlers = [
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, logging.StreamHandler)
            and str(getattr(getattr(handler, "stream", None), "name", "")).endswith("huginn.log")
        ]
        self.assertTrue(file_handlers)
        encoding = str(getattr(file_handlers[0].stream, "encoding", "")).lower().replace("-", "")
        self.assertEqual(encoding, "utf8")
        self.assertEqual(getattr(file_handlers[0].stream, "errors", None), "replace")
        configure_logging("./logs")

    def test_utf8_file_logging_roundtrip_with_accents_and_emoji(self) -> None:
        tmp_dir = Path("tests") / f"_tmp_huginn_runtime_{uuid.uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(str(tmp_dir))

        payload = "log utf8: noticias, inteligencia, acao, 🤖"
        logging.getLogger("huginn.tests").info(payload)
        for handler in logging.getLogger().handlers:
            handler.flush()

        content = (tmp_dir / "huginn.log").read_text(encoding="utf-8")
        self.assertIn(payload, content)
        configure_logging("./logs")

    def test_logger_writes_usage_and_report(self) -> None:
        tmp_dir = Path("tests") / "_tmp_huginn_logs"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        session_id = f"s-test-{uuid.uuid4().hex[:8]}"
        logger = SessionLogger(session_id=session_id, channel="tests", log_dir=str(tmp_dir))
        logger.add_usage(
            phase="loop",
            usage=TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                model=get_settings().deepseek_model_exec,
                provider="deepseek",
            ),
            note="unit-test",
        )
        report = logger.session_report()
        self.assertEqual(report["session_id"], session_id)
        self.assertEqual(len(report["entries"]), 1)
        self.assertGreaterEqual(report["totals"]["total_tokens"], 150)


if __name__ == "__main__":
    unittest.main()
