from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from typing import Awaitable, Callable

from huginn.channels.base import HuginnMessage
from huginn.channels.browser_base import SessionBrowser
from huginn.config import get_settings

logger = logging.getLogger("huginn.channels")


class InstagramChannel(SessionBrowser):
    INBOX_URL = "https://www.instagram.com/direct/inbox/"
    LOGIN_URL = "https://www.instagram.com/accounts/login/"
    THREAD_URL_TEMPLATE = "https://www.instagram.com/direct/t/{thread_id}/"
    AUTH_SELECTORS = [
        "a[href='/direct/inbox/']",
        "div[role='main']",
        "div[aria-label='Inbox']",
    ]
    THREAD_SELECTOR = "a[href*='/direct/t/']"
    THREAD_READY_SELECTORS = [
        "div[role='main']",
        "div[role='textbox'][contenteditable='true']",
        "textarea[placeholder*='Message']",
        "textarea[placeholder*='mensagem']",
    ]
    UNREAD_BADGE_SELECTORS = [
        "[aria-label*='unread']",
        "[aria-label*='nao lida']",
        "[aria-label*='não lida']",
        "[aria-label*='new message']",
        "svg[aria-label*='unread']",
        "span[aria-label*='unread']",
    ]
    UNREAD_MARKERS = [
        "unread",
        "nao lida",
        "não lida",
        "nova mensagem",
        "new message",
    ]
    COMPOSE_SELECTOR = (
        "div[role='textbox'][contenteditable='true'], "
        "textarea[placeholder*='Message'], "
        "textarea[placeholder*='mensagem']"
    )
    CHECKPOINT_MARKERS = ("/challenge/", "/accounts/suspended/")
    LOGIN_POPUP_LABELS = ("Not Now", "Agora nao", "Agora não", "Mais tarde")

    def __init__(
        self,
        *,
        session_dir: str,
        headless: bool = True,
        poll_interval: float = 10.0,
        on_message: Callable[[HuginnMessage], Awaitable[None]] | None = None,
        alert_callback: Callable[[str], Awaitable[None]] | None = None,
        username: str = "",
        password: str = "",
    ) -> None:
        settings = get_settings()
        super().__init__(
            name="instagram",
            base_url="https://www.instagram.com/",
            session_dir=session_dir,
            headless=headless,
            poll_interval=poll_interval,
            on_message=on_message,
            alert_callback=alert_callback,
        )
        self.username = (username or settings.instagram_username or "").strip()
        self.password = (password or settings.instagram_password or "").strip()
        self._seen_message_ids: set[str] = set()
        self._checkpoint_active = False
        self._checkpoint_alert_sent = False

    @property
    def seen_ids_path(self) -> Path:
        return self.session_dir / "seen_ids.json"

    @staticmethod
    def _is_checkpoint_url(url: str) -> bool:
        current = (url or "").strip().lower()
        if not current:
            return False
        return any(marker in current for marker in InstagramChannel.CHECKPOINT_MARKERS)

    @staticmethod
    def _extract_thread_id(href: str) -> str:
        raw = (href or "").strip()
        marker = "/direct/t/"
        if marker not in raw:
            return ""
        tail = raw.split(marker, 1)[1]
        return tail.split("/", 1)[0].strip()

    @staticmethod
    def _digest(value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return "empty"
        return hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()[:12]

    def _load_seen_ids(self) -> None:
        if not self.seen_ids_path.exists():
            self._seen_message_ids = set()
            logger.info("SESSION seen_ids missing channel=%s path=%s", self.name, str(self.seen_ids_path))
            return
        try:
            payload = json.loads(self.seen_ids_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                logger.warning(
                    "SESSION seen_ids invalid channel=%s type=%s",
                    self.name,
                    type(payload).__name__,
                )
                self._seen_message_ids = set()
                return
            self._seen_message_ids = {str(item).strip() for item in payload if str(item).strip()}
            logger.info(
                "SESSION seen_ids loaded channel=%s count=%d",
                self.name,
                len(self._seen_message_ids),
            )
        except Exception:
            logger.exception("SESSION seen_ids load error channel=%s", self.name)
            self._seen_message_ids = set()

    def _persist_seen_ids(self) -> None:
        try:
            payload = sorted(self._seen_message_ids)
            self.seen_ids_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "SESSION seen_ids saved channel=%s count=%d",
                self.name,
                len(self._seen_message_ids),
            )
        except Exception:
            logger.exception("SESSION seen_ids save error channel=%s", self.name)

    async def load_session(self) -> bool:
        loaded = await super().load_session()
        self._load_seen_ids()
        return loaded

    async def save_session(self) -> None:
        await super().save_session()
        self._persist_seen_ids()

    async def _notify_checkpoint(self, url: str) -> None:
        self._checkpoint_active = True
        logger.warning("INSTAGRAM checkpoint detected channel=%s url=%s", self.name, url)
        if self._checkpoint_alert_sent:
            return
        self._checkpoint_alert_sent = True
        if self.alert_callback is None:
            return
        try:
            await self.alert_callback(
                f"[Huginn:{self.name}] checkpoint de seguranca detectado: {url}"
            )
        except Exception:
            logger.exception("Falha ao enviar alerta de checkpoint channel=%s", self.name)

    async def _dismiss_login_popups(self) -> None:
        page = self._require_page()
        for label in self.LOGIN_POPUP_LABELS:
            try:
                button = page.get_by_role("button", name=label)
                if await button.count() > 0:
                    await button.first.click(timeout=1000)
                    await asyncio.sleep(0.2)
            except Exception:
                continue

    async def login(self) -> None:
        page = self._require_page()
        if not self.username or not self.password:
            raise RuntimeError("instagram credenciais ausentes (INSTAGRAM_USERNAME/INSTAGRAM_PASSWORD)")

        self._checkpoint_active = False
        logger.info("LOGIN start channel=%s", self.name)
        await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.fill("input[name='username']", self.username)
        await page.fill("input[name='password']", self.password)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(1200)
        current_url = str(getattr(page, "url", "") or "")
        if self._is_checkpoint_url(current_url):
            await self._notify_checkpoint(current_url)
            raise RuntimeError("instagram checkpoint detected")
        await self._dismiss_login_popups()
        await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=60000)
        await self._restore_local_storage()
        current_url = str(getattr(page, "url", "") or "")
        if self._is_checkpoint_url(current_url):
            await self._notify_checkpoint(current_url)
            raise RuntimeError("instagram checkpoint detected")
        if not await self.verify_auth():
            raise RuntimeError("instagram login falhou: inbox nao autenticada")
        self._checkpoint_active = False
        self._checkpoint_alert_sent = False
        logger.info("LOGIN done channel=%s", self.name)

    async def verify_auth(self) -> bool:
        page = self._require_page()
        logger.info("VERIFY_AUTH start channel=%s", self.name)
        try:
            await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=10000)
            await self._restore_local_storage()
            current_url = str(getattr(page, "url", "") or "")
            if self._is_checkpoint_url(current_url):
                await self._notify_checkpoint(current_url)
                logger.info("VERIFY_AUTH fail channel=%s", self.name)
                return False
            ok = await self._wait_for_any_selector(self.AUTH_SELECTORS, timeout_ms=10000)
            if ok:
                self._checkpoint_active = False
                self._checkpoint_alert_sent = False
            logger.info("VERIFY_AUTH %s channel=%s", "ok" if ok else "fail", self.name)
            return ok
        except Exception:
            logger.info("VERIFY_AUTH fail channel=%s", self.name)
            return False

    async def _collect_unread_threads(self) -> list[dict[str, str]]:
        page = self._require_page()
        raw = await page.evaluate(
            """
            (cfg) => {
                const out = [];
                const links = Array.from(document.querySelectorAll(cfg.threadSelector || "a[href*='/direct/t/']"));
                for (const link of links) {
                    const href = (link.getAttribute("href") || "").trim();
                    const match = href.match(/\\/direct\\/t\\/([^\\/?#]+)/);
                    const threadId = match ? String(match[1]).trim() : "";
                    if (!threadId) continue;

                    const row = link.closest("li, article, section, div[role='button'], div[role='listitem'], div");
                    const rowText = (row?.innerText || link.innerText || "").toLowerCase();
                    const rowLabel = (row?.getAttribute("aria-label") || "").toLowerCase();
                    const linkLabel = (link.getAttribute("aria-label") || "").toLowerCase();
                    const marker = `${rowText} ${rowLabel} ${linkLabel}`;

                    let hasUnread = false;
                    for (const markerText of cfg.unreadMarkers || []) {
                        if (marker.includes(String(markerText).toLowerCase())) {
                            hasUnread = true;
                            break;
                        }
                    }

                    if (!hasUnread && row) {
                        for (const selector of cfg.unreadBadgeSelectors || []) {
                            if (row.querySelector(selector)) {
                                hasUnread = true;
                                break;
                            }
                        }
                    }

                    if (!hasUnread) continue;
                    const title = (link.getAttribute("title") || "").trim();
                    const sender = title || (rowText.split("\\n")[0] || "").trim() || "unknown";
                    out.push({ thread_id: threadId, sender, href });
                }
                return out;
            }
            """,
            {
                "threadSelector": self.THREAD_SELECTOR,
                "unreadBadgeSelectors": self.UNREAD_BADGE_SELECTORS,
                "unreadMarkers": self.UNREAD_MARKERS,
            },
        )
        if not isinstance(raw, list):
            return []

        parsed: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            thread_id = self._extract_thread_id(str(item.get("href", ""))) or str(
                item.get("thread_id", "")
            ).strip()
            sender = str(item.get("sender", "")).strip() or "unknown"
            if not thread_id:
                continue
            parsed.append({"thread_id": thread_id, "sender": sender})
        return parsed

    async def _extract_latest_inbound_text(self, thread_id: str, sender_hint: str) -> str:
        page = self._require_page()
        target_url = self.THREAD_URL_TEMPLATE.format(thread_id=thread_id)
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        await self._restore_local_storage()
        await self._wait_for_any_selector(self.THREAD_READY_SELECTORS, timeout_ms=12000)
        raw: Any = await page.evaluate(
            """
            (cfg) => {
                const compose = document.querySelector(cfg.composeSelector || "");
                const composeContainer = compose
                    ? compose.closest("form, footer, div[role='presentation']")
                    : null;
                const nodes = Array.from(document.querySelectorAll("div[dir='auto'], span[dir='auto'], div[role='row']"));
                const texts = [];
                for (const node of nodes) {
                    if (!(node instanceof HTMLElement)) continue;
                    if (composeContainer && composeContainer.contains(node)) continue;
                    const value = (node.innerText || node.textContent || "").trim();
                    if (!value) continue;
                    const lower = value.toLowerCase();
                    if (
                        lower.startsWith("you sent") ||
                        lower.startsWith("voce enviou") ||
                        lower.startsWith("você enviou")
                    ) {
                        continue;
                    }
                    if (lower === "seen" || lower === "visto") {
                        continue;
                    }
                    texts.push(value);
                }
                if (!texts.length) return "";
                return texts[texts.length - 1];
            }
            """,
            {
                "composeSelector": self.COMPOSE_SELECTOR,
            },
        )
        text = str(raw or "").strip()
        if text:
            return text
        return f"Nova mensagem Instagram de {sender_hint}"

    async def poll_messages(self) -> list[HuginnMessage]:
        if self._checkpoint_active:
            return []
        page = self._require_page()
        await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=30000)
        await self._restore_local_storage()
        current_url = str(getattr(page, "url", "") or "")
        if self._is_checkpoint_url(current_url):
            await self._notify_checkpoint(current_url)
            return []
        unread_threads = await self._collect_unread_threads()
        current_unread = {thread["thread_id"] for thread in unread_threads if thread.get("thread_id")}

        before_cleanup = set(self._seen_message_ids)
        self._seen_message_ids.intersection_update(current_unread)
        seen_changed = self._seen_message_ids != before_cleanup

        messages: list[HuginnMessage] = []
        for thread in unread_threads:
            thread_id = thread.get("thread_id", "").strip()
            sender = thread.get("sender", "").strip() or "unknown"
            if not thread_id or thread_id in self._seen_message_ids:
                continue
            try:
                full_text = await self._extract_latest_inbound_text(thread_id, sender)
            except Exception:
                logger.exception(
                    "POLL thread extract error channel=%s thread_id=%s",
                    self.name,
                    thread_id,
                )
                continue

            # Known edge case: crash between thread open (mark-as-read) and seen_ids persistence can lose one message.
            self._seen_message_ids.add(thread_id)
            seen_changed = True
            digest = self._digest(full_text)
            message_id = f"{thread_id}:{digest}"
            session_id = f"{self.name}-{thread_id}-{digest[:8]}"
            messages.append(
                HuginnMessage(
                    channel=self.name,
                    sender=sender,
                    text=full_text,
                    session_id=session_id,
                    metadata={
                        "thread_id": thread_id,
                        "message_id": message_id,
                        "recipient": sender,
                    },
                )
            )

        if seen_changed:
            self._persist_seen_ids()
        return messages

    async def send(self, recipient: str, text: str) -> None:
        page = self._require_page()
        recipient = (recipient or "").strip()
        text = (text or "").strip()
        if not recipient:
            raise RuntimeError("instagram recipient vazio")
        if not text:
            raise RuntimeError("instagram text vazio")

        await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=30000)
        await self._restore_local_storage()
        clicked = await page.evaluate(
            """
            (target) => {
                const query = String(target || "").trim().toLowerCase();
                if (!query) return false;
                const links = Array.from(document.querySelectorAll("a[href*='/direct/t/']"));
                for (const link of links) {
                    const text = (link.innerText || "").trim().toLowerCase();
                    if (text.includes(query)) {
                        link.click();
                        return true;
                    }
                }
                return false;
            }
            """,
            recipient,
        )
        if not clicked:
            logger.warning(
                "SEND thread not found channel=%s recipient=%s",
                self.name,
                recipient,
            )
            return

        await page.wait_for_selector(self.COMPOSE_SELECTOR, timeout=15000)
        await page.click(self.COMPOSE_SELECTOR, timeout=15000)
        await page.keyboard.type(text)
        await page.keyboard.press("Enter")
