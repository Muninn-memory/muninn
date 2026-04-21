from __future__ import annotations

import asyncio
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import huginn.server as server
from huginn.channels.base import HuginnMessage
from huginn.channels.browser_base import SessionBrowser
from huginn.channels.instagram import InstagramChannel
from huginn.channels.whatsapp import WhatsAppChannel


async def _noop_on_message(_message: HuginnMessage) -> None:
    return


@contextmanager
def _tmp_session_dir():
    session_path = Path("tests") / f"_tmp_huginn_phase7_{uuid.uuid4().hex[:8]}"
    session_path.mkdir(parents=True, exist_ok=True)
    try:
        yield str(session_path)
    finally:
        shutil.rmtree(session_path, ignore_errors=True)


class _DummyBrowser(SessionBrowser):
    def __init__(
        self,
        *,
        session_dir: str,
        on_message=None,
        poll_interval: float = 0.01,
    ) -> None:
        super().__init__(
            name="dummy",
            base_url="https://example.com/",
            session_dir=session_dir,
            headless=True,
            poll_interval=poll_interval,
            on_message=on_message,
        )
        self.poll_batches: list[list[HuginnMessage]] = []
        self.sent: list[tuple[str, str]] = []
        self.poll_exception: Exception | None = None
        self.poll_exception_repeat = False

    async def login(self) -> None:
        return

    async def verify_auth(self) -> bool:
        return True

    async def poll_messages(self) -> list[HuginnMessage]:
        if self.poll_exception is not None:
            exc = self.poll_exception
            if not self.poll_exception_repeat:
                self.poll_exception = None
            raise exc
        if self.poll_batches:
            batch = self.poll_batches.pop(0)
        else:
            batch = []
        if not self.poll_batches and self.poll_exception is None:
            self._running = False
        return batch

    async def send(self, recipient: str, text: str) -> None:
        self.sent.append((recipient, text))


class SessionBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_and_load_session_roundtrip(self) -> None:
        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            browser._context = SimpleNamespace(
                cookies=AsyncMock(
                    return_value=[{"name": "sid", "value": "v", "domain": "example.com", "path": "/"}]
                ),
                add_cookies=AsyncMock(),
                add_init_script=AsyncMock(),
            )
            browser._page = SimpleNamespace(
                evaluate=AsyncMock(return_value=[["token", "abc"], ["locale", "pt-BR"]])
            )

            await browser.save_session()
            self.assertTrue((Path(td) / "cookies.json").exists())
            self.assertTrue((Path(td) / "storage.json").exists())

            loader = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            loader._context = SimpleNamespace(
                add_cookies=AsyncMock(),
            )
            loaded = await loader.load_session()

            self.assertTrue(loaded)
            loader._context.add_cookies.assert_awaited_once()

    async def test_restore_local_storage_current_payload_format(self) -> None:
        with _tmp_session_dir() as td:
            storage = {
                "origin": "https://example.com",
                "items": {"k1": "v1", "k2": "v2"},
            }
            (Path(td) / "storage.json").write_text(json.dumps(storage), encoding="utf-8")
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            browser._page = SimpleNamespace(
                url="https://example.com/",
                evaluate=AsyncMock(),
            )

            await browser._restore_local_storage()

            browser._page.evaluate.assert_awaited_once()
            args = browser._page.evaluate.await_args.args
            self.assertEqual(args[1], {"k1": "v1", "k2": "v2"})

    async def test_restore_local_storage_legacy_payload_format(self) -> None:
        with _tmp_session_dir() as td:
            storage = {"legacy_key": "legacy_value"}
            (Path(td) / "storage.json").write_text(json.dumps(storage), encoding="utf-8")
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            browser._page = SimpleNamespace(
                url="https://example.com/",
                evaluate=AsyncMock(),
            )

            await browser._restore_local_storage()

            browser._page.evaluate.assert_awaited_once()
            args = browser._page.evaluate.await_args.args
            self.assertEqual(args[1], {"legacy_key": "legacy_value"})

    async def test_restore_local_storage_skips_origin_mismatch(self) -> None:
        with _tmp_session_dir() as td:
            storage = {
                "origin": "https://other.example.com",
                "items": {"k1": "v1"},
            }
            (Path(td) / "storage.json").write_text(json.dumps(storage), encoding="utf-8")
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            browser._page = SimpleNamespace(
                url="https://example.com/",
                evaluate=AsyncMock(),
            )

            await browser._restore_local_storage()

            browser._page.evaluate.assert_not_called()

    async def test_restore_local_storage_invalid_json_logs_error(self) -> None:
        with _tmp_session_dir() as td:
            (Path(td) / "storage.json").write_text("{invalid", encoding="utf-8")
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            browser._page = SimpleNamespace(
                url="https://example.com/",
                evaluate=AsyncMock(),
            )

            with self.assertLogs("huginn.channels", level="ERROR") as logs:
                await browser._restore_local_storage()

            self.assertTrue(
                any("SESSION localStorage restore error channel=dummy" in line for line in logs.output)
            )
            browser._page.evaluate.assert_not_called()

    async def test_run_poll_loop_dispatches_messages_from_callback(self) -> None:
        received: list[str] = []

        async def _on_message(message: HuginnMessage) -> None:
            received.append(message.text)

        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=_on_message, poll_interval=0.01)
            browser.poll_batches = [
                [
                    HuginnMessage(
                        channel="dummy",
                        sender="alice",
                        text="hello",
                        session_id="dummy-1",
                        metadata={"message_id": "m-1"},
                    )
                ]
            ]
            await browser.run_poll_loop()

        self.assertEqual(received, ["hello"])

    async def test_run_poll_loop_without_callback_logs_warning_and_keeps_loop(self) -> None:
        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=None)
            browser.poll_batches = [
                [
                    HuginnMessage(
                        channel="dummy",
                        sender="alice",
                        text="hello",
                        session_id="dummy-1",
                        metadata={"message_id": "m-1"},
                    )
                ]
            ]
            with self.assertLogs("huginn.channels", level="WARNING") as logs:
                await browser.run_poll_loop()
            self.assertTrue(
                any("POLL message received but on_message is None channel=dummy" in line for line in logs.output)
            )

    async def test_run_poll_loop_does_not_call_verify_auth_per_cycle(self) -> None:
        received: list[str] = []

        async def _on_message(message: HuginnMessage) -> None:
            received.append(message.text)

        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=_on_message, poll_interval=0.01)
            browser.verify_auth = AsyncMock(return_value=True)  # type: ignore[method-assign]
            browser.poll_batches = [
                [
                    HuginnMessage(
                        channel="dummy",
                        sender="alice",
                        text="hello",
                        session_id="dummy-1",
                        metadata={"message_id": "m-1"},
                    )
                ]
            ]
            await browser.run_poll_loop()

        self.assertEqual(received, ["hello"])
        browser.verify_auth.assert_not_called()

    async def test_run_poll_loop_auth_error_triggers_reauth(self) -> None:
        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message, poll_interval=0.01)
            browser._page = object()
            browser._context = object()
            browser._browser = object()
            browser.poll_exception = RuntimeError("Target page, context or browser has been closed")
            browser.login = AsyncMock()  # type: ignore[method-assign]
            browser.verify_auth = AsyncMock(return_value=True)  # type: ignore[method-assign]
            browser.save_session = AsyncMock()  # type: ignore[method-assign]

            with self.assertLogs("huginn.channels", level="INFO") as logs:
                await browser.run_poll_loop()

        browser.login.assert_awaited_once()
        browser.verify_auth.assert_awaited_once()
        browser.save_session.assert_awaited_once()
        self.assertTrue(any("REAUTH start channel=dummy" in line for line in logs.output))
        self.assertTrue(any("REAUTH success channel=dummy" in line for line in logs.output))

    async def test_run_poll_loop_non_auth_error_does_not_trigger_reauth(self) -> None:
        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message, poll_interval=0.01)
            browser._page = object()
            browser._context = object()
            browser._browser = object()
            browser.poll_exception = RuntimeError("temporary parse failure")
            browser.login = AsyncMock()  # type: ignore[method-assign]
            browser.verify_auth = AsyncMock(return_value=True)  # type: ignore[method-assign]
            browser.save_session = AsyncMock()  # type: ignore[method-assign]

            with self.assertLogs("huginn.channels", level="ERROR") as logs:
                await browser.run_poll_loop()

        browser.login.assert_not_called()
        browser.verify_auth.assert_not_called()
        browser.save_session.assert_not_called()
        self.assertTrue(any("POLL error channel=dummy" in line for line in logs.output))

    async def test_stop_cancels_poll_task_and_closes_runtime(self) -> None:
        with _tmp_session_dir() as td:
            browser = _DummyBrowser(session_dir=td, on_message=_noop_on_message)
            page = SimpleNamespace(close=AsyncMock())
            context = SimpleNamespace(close=AsyncMock())
            runtime_browser = SimpleNamespace(close=AsyncMock())
            playwright = SimpleNamespace(stop=AsyncMock())
            browser._page = page
            browser._context = context
            browser._browser = runtime_browser
            browser._playwright = playwright

            async def _forever() -> None:
                while True:
                    await asyncio.sleep(1.0)

            task = asyncio.create_task(_forever())
            browser._poll_task = task
            browser._running = True

            await browser.stop()

            self.assertTrue(task.done())
            page.close.assert_awaited_once()
            context.close.assert_awaited_once()
            runtime_browser.close.assert_awaited_once()
            playwright.stop.assert_awaited_once()


class WhatsAppChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_auth_true_and_false(self) -> None:
        with _tmp_session_dir() as td:
            channel = WhatsAppChannel(session_dir=td, on_message=_noop_on_message)
            channel._page = SimpleNamespace(goto=AsyncMock())
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            channel._wait_for_any_selector = AsyncMock(return_value=True)  # type: ignore[method-assign]
            self.assertTrue(await channel.verify_auth())
            channel._restore_local_storage.assert_awaited_once()

            channel._page = SimpleNamespace(goto=AsyncMock(side_effect=RuntimeError("boom")))
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            self.assertFalse(await channel.verify_auth())
            channel._restore_local_storage.assert_not_called()

    async def test_verify_auth_restores_storage_before_selector_check(self) -> None:
        with _tmp_session_dir() as td:
            channel = WhatsAppChannel(session_dir=td, on_message=_noop_on_message)
            call_order: list[str] = []

            async def _goto(*_args, **_kwargs):
                call_order.append("goto")

            async def _restore():
                call_order.append("restore")

            async def _wait(*_args, **_kwargs):
                call_order.append("wait")
                return True

            channel._page = SimpleNamespace(goto=AsyncMock(side_effect=_goto))
            channel._restore_local_storage = AsyncMock(side_effect=_restore)  # type: ignore[method-assign]
            channel._wait_for_any_selector = AsyncMock(side_effect=_wait)  # type: ignore[method-assign]

            ok = await channel.verify_auth()
            self.assertTrue(ok)
            self.assertEqual(call_order, ["goto", "restore", "wait"])

    async def test_poll_messages_dedupes_by_id_and_filters_sender(self) -> None:
        with _tmp_session_dir() as td:
            channel = WhatsAppChannel(
                session_dir=td,
                on_message=_noop_on_message,
                allowed_sender="+55 11 99999-0000",
            )
            channel._page = SimpleNamespace(
                evaluate=AsyncMock(
                    return_value=[
                        {"id": "m1", "sender": "5511999990000", "text": "primeira"},
                        {"id": "m1", "sender": "5511999990000", "text": "duplicada"},
                        {"id": "m2", "sender": "outro", "text": "ignorar"},
                    ]
                )
            )

            first = await channel.poll_messages()
            second = await channel.poll_messages()

            self.assertEqual(len(first), 1)
            self.assertEqual(first[0].sender, "5511999990000")
            self.assertEqual(len(second), 0)

    async def test_send_supports_phone_and_chat_search_fallback(self) -> None:
        with _tmp_session_dir() as td:
            keyboard = SimpleNamespace(press=AsyncMock(), type=AsyncMock())
            page = SimpleNamespace(
                goto=AsyncMock(),
                wait_for_selector=AsyncMock(),
                click=AsyncMock(),
                fill=AsyncMock(),
                keyboard=keyboard,
            )
            channel = WhatsAppChannel(session_dir=td, on_message=_noop_on_message)
            channel._page = page

            await channel.send("+55 (11) 99999-0000", "oi")
            self.assertIn("send?phone=5511999990000", page.goto.call_args.args[0])

            await channel.send("alice", "hello")
            page.fill.assert_awaited()
            keyboard.type.assert_awaited()


class InstagramChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_auth_true_and_false(self) -> None:
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._page = SimpleNamespace(
                goto=AsyncMock(),
                url="https://www.instagram.com/direct/inbox/",
            )
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            channel._wait_for_any_selector = AsyncMock(return_value=True)  # type: ignore[method-assign]
            self.assertTrue(await channel.verify_auth())
            channel._restore_local_storage.assert_awaited_once()

            channel._page = SimpleNamespace(
                goto=AsyncMock(side_effect=RuntimeError("boom")),
                url="https://www.instagram.com/direct/inbox/",
            )
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            self.assertFalse(await channel.verify_auth())
            channel._restore_local_storage.assert_not_called()

    async def test_verify_auth_checkpoint_returns_false_and_alerts(self) -> None:
        alert = AsyncMock()
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                alert_callback=alert,
                username="user",
                password="pass",
            )
            channel._page = SimpleNamespace(
                goto=AsyncMock(),
                url="https://www.instagram.com/challenge/abc",
            )
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            channel._wait_for_any_selector = AsyncMock(return_value=True)  # type: ignore[method-assign]

            ok = await channel.verify_auth()

            self.assertFalse(ok)
            alert.assert_awaited_once()
            channel._wait_for_any_selector.assert_not_called()

    async def test_login_checkpoint_raises_runtime_error(self) -> None:
        alert = AsyncMock()
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                alert_callback=alert,
                username="user",
                password="pass",
            )
            channel._page = SimpleNamespace(
                goto=AsyncMock(),
                fill=AsyncMock(),
                click=AsyncMock(),
                wait_for_timeout=AsyncMock(),
                url="https://www.instagram.com/challenge/abc",
            )

            with self.assertRaises(RuntimeError):
                await channel.login()

            alert.assert_awaited_once()

    async def test_verify_auth_restores_storage_before_selector_check(self) -> None:
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            call_order: list[str] = []

            async def _goto(*_args, **_kwargs):
                call_order.append("goto")

            async def _restore():
                call_order.append("restore")

            async def _wait(*_args, **_kwargs):
                call_order.append("wait")
                return True

            channel._page = SimpleNamespace(
                goto=AsyncMock(side_effect=_goto),
                url="https://www.instagram.com/direct/inbox/",
            )
            channel._restore_local_storage = AsyncMock(side_effect=_restore)  # type: ignore[method-assign]
            channel._wait_for_any_selector = AsyncMock(side_effect=_wait)  # type: ignore[method-assign]

            ok = await channel.verify_auth()
            self.assertTrue(ok)
            self.assertEqual(call_order, ["goto", "restore", "wait"])

    async def test_poll_messages_returns_full_text_for_unread_threads(self) -> None:
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._page = SimpleNamespace(
                goto=AsyncMock(),
                url="https://www.instagram.com/direct/inbox/",
            )
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            channel._collect_unread_threads = AsyncMock(  # type: ignore[method-assign]
                return_value=[{"thread_id": "th1", "sender": "alice"}]
            )
            channel._extract_latest_inbound_text = AsyncMock(  # type: ignore[method-assign]
                return_value="mensagem completa da thread"
            )
            channel._persist_seen_ids = Mock()  # type: ignore[method-assign]

            messages = await channel.poll_messages()

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].text, "mensagem completa da thread")
            self.assertEqual(messages[0].metadata.get("thread_id"), "th1")
            channel._extract_latest_inbound_text.assert_awaited_once_with("th1", "alice")

    async def test_poll_messages_dedupe_with_intersection(self) -> None:
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._page = SimpleNamespace(
                goto=AsyncMock(),
                url="https://www.instagram.com/direct/inbox/",
            )
            channel._restore_local_storage = AsyncMock()  # type: ignore[method-assign]
            channel._collect_unread_threads = AsyncMock(  # type: ignore[method-assign]
                side_effect=[
                    [{"thread_id": "th1", "sender": "alice"}],
                    [{"thread_id": "th1", "sender": "alice"}],
                    [],
                    [{"thread_id": "th1", "sender": "alice"}],
                ]
            )
            channel._extract_latest_inbound_text = AsyncMock(  # type: ignore[method-assign]
                side_effect=["msg-1", "msg-2"]
            )
            channel._persist_seen_ids = Mock()  # type: ignore[method-assign]

            first = await channel.poll_messages()
            second = await channel.poll_messages()
            third = await channel.poll_messages()
            fourth = await channel.poll_messages()

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 0)
            self.assertEqual(len(third), 0)
            self.assertEqual(len(fourth), 1)
            self.assertEqual(fourth[0].text, "msg-2")

    async def test_seen_ids_load_and_missing_file_are_graceful(self) -> None:
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._context = SimpleNamespace(add_cookies=AsyncMock())
            channel.seen_ids_path.write_text(json.dumps(["th1", "th2"]), encoding="utf-8")

            await channel.load_session()
            self.assertEqual(channel._seen_message_ids, {"th1", "th2"})

        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._context = SimpleNamespace(add_cookies=AsyncMock())

            await channel.load_session()
            self.assertEqual(channel._seen_message_ids, set())

    async def test_save_session_persists_seen_ids(self) -> None:
        with _tmp_session_dir() as td:
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._seen_message_ids = {"th3", "th1"}
            channel._context = SimpleNamespace(
                cookies=AsyncMock(
                    return_value=[{"name": "sid", "value": "v", "domain": "instagram.com", "path": "/"}]
                )
            )
            channel._page = SimpleNamespace(
                evaluate=AsyncMock(return_value=[["k", "v"]]),
            )

            await channel.save_session()

            self.assertTrue(channel.seen_ids_path.exists())
            payload = json.loads(channel.seen_ids_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, ["th1", "th3"])

    async def test_send_uses_thread_lookup_and_compose(self) -> None:
        with _tmp_session_dir() as td:
            keyboard = SimpleNamespace(press=AsyncMock(), type=AsyncMock())
            page = SimpleNamespace(
                goto=AsyncMock(),
                evaluate=AsyncMock(return_value=True),
                wait_for_selector=AsyncMock(),
                click=AsyncMock(),
                keyboard=keyboard,
            )
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._page = page
            await channel.send("alice", "hello ig")

            page.goto.assert_awaited()
            page.evaluate.assert_awaited()
            keyboard.type.assert_awaited_once()
            keyboard.press.assert_awaited_once()

    async def test_send_without_thread_found_logs_warning(self) -> None:
        with _tmp_session_dir() as td:
            keyboard = SimpleNamespace(press=AsyncMock(), type=AsyncMock())
            page = SimpleNamespace(
                goto=AsyncMock(),
                evaluate=AsyncMock(return_value=False),
                wait_for_selector=AsyncMock(),
                click=AsyncMock(),
                keyboard=keyboard,
            )
            channel = InstagramChannel(
                session_dir=td,
                on_message=_noop_on_message,
                username="user",
                password="pass",
            )
            channel._page = page

            with self.assertLogs("huginn.channels", level="WARNING") as logs:
                await channel.send("missing-recipient", "hello ig")

            self.assertTrue(
                any("SEND thread not found channel=instagram recipient=missing-recipient" in line for line in logs.output)
            )
            keyboard.type.assert_not_called()


class _FailChannel:
    async def start(self) -> None:
        raise RuntimeError("startup failed")

    async def stop(self) -> None:
        return

    async def send_message(self, _recipient: str, _text: str) -> None:
        return

    async def run_poll_loop(self) -> None:
        return


class _OkChannel:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_message(self, _recipient: str, _text: str) -> None:
        return

    async def run_poll_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise


class ServerChannelStartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        server._whatsapp_channel = None
        server._instagram_channel = None
        server._whatsapp_task = None
        server._instagram_task = None

    async def asyncTearDown(self) -> None:
        await server.shutdown_event()

    async def test_disabled_channels_keep_runtime_none(self) -> None:
        settings = SimpleNamespace(
            browser_tools_enabled=False,
            browser_headless=True,
            whatsapp_enabled=False,
            instagram_enabled=False,
        )
        with patch("huginn.server.get_settings", return_value=settings):
            await server.startup_event()

        self.assertIsNone(server._whatsapp_channel)
        self.assertIsNone(server._instagram_channel)
        self.assertIsNone(server._whatsapp_task)
        self.assertIsNone(server._instagram_task)

    async def test_whatsapp_startup_failure_does_not_block_instagram(self) -> None:
        settings = SimpleNamespace(browser_tools_enabled=False, browser_headless=True)
        with patch("huginn.server.get_settings", return_value=settings), patch(
            "huginn.server._init_optional_channels", return_value=None
        ):
            server._whatsapp_channel = _FailChannel()  # type: ignore[assignment]
            server._instagram_channel = _OkChannel()  # type: ignore[assignment]
            await server.startup_event()

        self.assertIsNone(server._whatsapp_channel)
        self.assertIsNone(server._whatsapp_task)
        self.assertIsNotNone(server._instagram_channel)
        self.assertIsNotNone(server._instagram_task)

    async def test_instagram_startup_failure_does_not_block_whatsapp(self) -> None:
        settings = SimpleNamespace(browser_tools_enabled=False, browser_headless=True)
        with patch("huginn.server.get_settings", return_value=settings), patch(
            "huginn.server._init_optional_channels", return_value=None
        ):
            server._whatsapp_channel = _OkChannel()  # type: ignore[assignment]
            server._instagram_channel = _FailChannel()  # type: ignore[assignment]
            await server.startup_event()

        self.assertIsNotNone(server._whatsapp_channel)
        self.assertIsNotNone(server._whatsapp_task)
        self.assertIsNone(server._instagram_channel)
        self.assertIsNone(server._instagram_task)


if __name__ == "__main__":
    unittest.main()
