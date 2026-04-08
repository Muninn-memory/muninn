from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from huginn.channels.base import ChannelAdapter, HuginnMessage

logger = logging.getLogger("huginn.channels")

try:  # optional runtime dependency
    from playwright_stealth import stealth_async
except Exception:  # pragma: no cover - optional dependency
    stealth_async = None


def _clip(value: object, max_chars: int = 80) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


class SessionBrowser(ChannelAdapter, ABC):
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        session_dir: str,
        headless: bool = True,
        poll_interval: float = 5.0,
        on_message: Callable[[HuginnMessage], Awaitable[None]] | None = None,
        alert_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._name = (name or "").strip().lower()
        self.base_url = (base_url or "").strip()
        self.session_dir = Path(session_dir).resolve()
        self.headless = bool(headless)
        self.poll_interval = max(float(poll_interval), 0.5)
        self.on_message = on_message
        self.alert_callback = alert_callback

        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None

        self._running = False
        self._poll_task: asyncio.Task[None] | None = None
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._session_origin = self._resolve_origin(self.base_url)

        self.session_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return self._name

    @property
    def cookies_path(self) -> Path:
        return self.session_dir / "cookies.json"

    @property
    def storage_path(self) -> Path:
        return self.session_dir / "storage.json"

    @staticmethod
    def _resolve_origin(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return ""

    def _import_async_playwright(self):
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError(f"playwright unavailable: {exc}") from exc
        return async_playwright

    async def _apply_stealth(self, page: Any) -> None:
        if stealth_async is None:
            return
        try:
            await stealth_async(page)
        except Exception:
            logger.debug("STEALTH unavailable channel=%s", self.name)

    def _require_page(self) -> Any:
        if self._page is None:
            raise RuntimeError(f"{self.name}: page not initialized")
        return self._page

    async def _wait_for_any_selector(self, selectors: list[str], *, timeout_ms: int) -> bool:
        page = self._require_page()
        if not selectors:
            return False
        each_timeout = max(500, int(timeout_ms / max(1, len(selectors))))
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=each_timeout)
                return True
            except Exception:
                continue
        return False

    async def _notify_auth_failure(self, reason: str) -> None:
        logger.warning("VERIFY_AUTH fail channel=%s reason=%.200r", self.name, _clip(reason, 200))
        if self.alert_callback is None:
            return
        try:
            await self.alert_callback(
                f"[Huginn:{self.name}] sessao expirada ou invalida. Motivo: {reason}"
            )
        except Exception:
            logger.exception("Falha ao enviar alerta de sessao channel=%s", self.name)

    def _mark_seen(self, key: str) -> bool:
        normalized = (key or "").strip()
        if not normalized:
            return False
        if normalized in self._seen_ids:
            return False
        self._seen_ids[normalized] = None
        if len(self._seen_ids) > 5000:
            self._seen_ids.popitem(last=False)
        return True

    def _is_auth_or_session_error(self, exc: Exception) -> bool:
        if self._page is None or self._context is None or self._browser is None:
            return True
        message = str(exc or "").strip().lower()
        if not message:
            return False
        markers = (
            "target page, context or browser has been closed",
            "browser has been closed",
            "context has been closed",
            "page has been closed",
            "chrome-error://chromewebdata",
            "navigation to",
            "login required",
            "session expired",
            "not logged",
        )
        return any(marker in message for marker in markers)

    async def _recover_auth_session(self, reason: str) -> bool:
        logger.warning("REAUTH start channel=%s reason=%.200r", self.name, _clip(reason, 200))
        try:
            await self.login()
            if not await self.verify_auth():
                await self._notify_auth_failure("re-login nao restaurou sessao")
                logger.warning("REAUTH fail channel=%s reason='re-login nao restaurou sessao'", self.name)
                return False
            await self.save_session()
            logger.info("REAUTH success channel=%s", self.name)
            return True
        except Exception as exc:
            await self._notify_auth_failure(str(exc))
            logger.warning("REAUTH fail channel=%s reason=%.200r", self.name, _clip(exc, 200))
            return False

    def _message_dedupe_key(self, message: HuginnMessage) -> str:
        metadata = message.metadata or {}
        for key in ("message_id", "id", "thread_id"):
            value = str(metadata.get(key, "")).strip()
            if value:
                return f"{self.name}:{value}"
        return f"{self.name}:{message.session_id}:{message.sender}:{_clip(message.text, 120)}"

    async def start(self) -> None:
        if self._context is not None and self._page is not None:
            return

        logger.info("SESSION start channel=%s dir=%s", self.name, str(self.session_dir))
        try:
            async_playwright = self._import_async_playwright()
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context()
            loaded = await self.load_session()
            self._page = await self._context.new_page()
            await self._apply_stealth(self._page)

            authenticated = await self.verify_auth()
            if not authenticated:
                await self.login()
                authenticated = await self.verify_auth()
                if not authenticated:
                    await self._notify_auth_failure("falha de autenticacao no startup")
                    raise RuntimeError(f"{self.name}: authentication failed during startup")

            await self.save_session()
            self._running = True
            logger.info("SESSION ready channel=%s loaded=%s", self.name, loaded)
        except Exception:
            await self._close_runtime()
            raise

    async def stop(self) -> None:
        self._running = False
        task = self._poll_task
        if task is not None and not task.done():
            current = asyncio.current_task()
            if task is not current:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("POLL stop error channel=%s", self.name)
        await self._close_runtime()
        logger.info("SESSION stop channel=%s", self.name)

    async def _close_runtime(self) -> None:
        page, context, browser, playwright = (
            self._page,
            self._context,
            self._browser,
            self._playwright,
        )
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    async def load_session(self) -> bool:
        context = self._context
        if context is None:
            raise RuntimeError(f"{self.name}: context not initialized")

        if not self.cookies_path.exists():
            return False

        try:
            cookies_payload = json.loads(self.cookies_path.read_text(encoding="utf-8"))
            if isinstance(cookies_payload, list):
                await context.add_cookies(cookies_payload)
            else:
                logger.warning(
                    "SESSION cookies payload invalid channel=%s type=%s",
                    self.name,
                    type(cookies_payload).__name__,
                )
                await context.add_cookies([])
            logger.info("SESSION loaded channel=%s dir=%s", self.name, str(self.session_dir))
            return True
        except Exception:
            logger.exception("SESSION load error channel=%s", self.name)
            return False

    def _parse_storage_payload(self) -> tuple[str, dict[str, str]] | None:
        if not self.storage_path.exists():
            return None
        payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None

        if isinstance(payload.get("items"), dict):
            origin = str(payload.get("origin", "")).strip() or self._session_origin
            items = {str(k): str(v) for k, v in payload["items"].items()}
            return origin, items

        legacy_items = {str(k): str(v) for k, v in payload.items()}
        return self._session_origin, legacy_items

    async def _restore_local_storage(self) -> None:
        if not self.storage_path.exists():
            return
        page = self._require_page()
        try:
            parsed = self._parse_storage_payload()
            if parsed is None:
                return
            expected_origin, items = parsed
            if not items:
                return

            current_origin = self._resolve_origin(str(getattr(page, "url", "") or ""))
            normalized_expected = self._resolve_origin(expected_origin) or self._session_origin
            if normalized_expected and current_origin and normalized_expected != current_origin:
                logger.debug(
                    "SESSION localStorage skipped channel=%s current=%s expected=%s",
                    self.name,
                    current_origin,
                    normalized_expected,
                )
                return

            await page.evaluate(
                """
                (items) => {
                    for (const [key, value] of Object.entries(items || {})) {
                        window.localStorage.setItem(key, String(value));
                    }
                }
                """,
                items,
            )
            logger.info(
                "SESSION localStorage restored channel=%s keys=%d",
                self.name,
                len(items),
            )
        except Exception:
            logger.exception("SESSION localStorage restore error channel=%s", self.name)

    async def save_session(self) -> None:
        context = self._context
        page = self._page
        if context is None:
            raise RuntimeError(f"{self.name}: context not initialized")

        cookies = await context.cookies()
        self.cookies_path.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        items: dict[str, str] = {}
        if page is not None:
            try:
                raw_entries = await page.evaluate("() => Object.entries(window.localStorage || {})")
                if isinstance(raw_entries, list):
                    for item in raw_entries:
                        if isinstance(item, list) and len(item) == 2:
                            key = str(item[0])
                            value = str(item[1])
                            items[key] = value
            except Exception:
                logger.debug("SESSION save localStorage failed channel=%s", self.name)

        storage_payload = {"origin": self._session_origin, "items": items}
        self.storage_path.write_text(
            json.dumps(storage_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("SESSION saved channel=%s dir=%s", self.name, str(self.session_dir))

    async def run_poll_loop(self) -> None:
        current_task = asyncio.current_task()
        self._poll_task = current_task  # type: ignore[assignment]
        self._running = True
        logger.info("POLL start channel=%s interval=%.1fs", self.name, self.poll_interval)
        try:
            while self._running:
                try:
                    incoming = await self.poll_messages()
                    if incoming:
                        logger.info("POLL channel=%s count=%d", self.name, len(incoming))
                    for message in incoming:
                        key = self._message_dedupe_key(message)
                        if not self._mark_seen(key):
                            continue
                        logger.info(
                            "RECV channel=%s sender=%s text=%.80r",
                            message.channel,
                            message.sender,
                            _clip(message.text, 80),
                        )
                        if self.on_message is None:
                            logger.warning(
                                "POLL message received but on_message is None channel=%s",
                                self.name,
                            )
                            logger.info(
                                "POLL dropped channel=%s sender=%s reason=no_on_message",
                                self.name,
                                message.sender,
                            )
                            continue
                        await self.on_message(message)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if self._is_auth_or_session_error(exc):
                        await self._recover_auth_session(str(exc))
                    else:
                        logger.exception("POLL error channel=%s", self.name)
                await asyncio.sleep(self.poll_interval)
        finally:
            if self._poll_task is current_task:
                self._poll_task = None
            logger.info("POLL stop channel=%s", self.name)

    async def send_message(self, recipient: str, text: str) -> None:
        logger.info(
            "SEND channel=%s recipient=%s text=%.80r",
            self.name,
            recipient,
            _clip(text, 80),
        )
        try:
            await self.send(recipient, text)
        except Exception:
            logger.exception("SEND error channel=%s recipient=%s", self.name, recipient)
            raise

    @abstractmethod
    async def login(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def verify_auth(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def poll_messages(self) -> list[HuginnMessage]:
        raise NotImplementedError

    @abstractmethod
    async def send(self, recipient: str, text: str) -> None:
        raise NotImplementedError
