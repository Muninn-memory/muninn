from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from huginn.channels.base import HuginnMessage
from huginn.channels.browser_base import SessionBrowser
from huginn.config import get_settings

logger = logging.getLogger("huginn.channels")


class InstagramChannel(SessionBrowser):
    INBOX_URL = "https://www.instagram.com/direct/inbox/"
    LOGIN_URL = "https://www.instagram.com/accounts/login/"
    AUTH_SELECTORS = [
        "a[href='/direct/inbox/']",
        "div[role='main']",
        "div[aria-label='Inbox']",
    ]
    THREAD_SELECTOR = "a[href*='/direct/t/']"
    COMPOSE_SELECTOR = "div[role='textbox'][contenteditable='true'], textarea[placeholder*='Message'], textarea[placeholder*='mensagem']"

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

    async def _dismiss_login_popups(self) -> None:
        page = self._require_page()
        for label in ("Not Now", "Agora nao", "Mais tarde"):
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

        logger.info("LOGIN start channel=%s", self.name)
        await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.fill("input[name='username']", self.username)
        await page.fill("input[name='password']", self.password)
        await page.click("button[type='submit']")
        await page.wait_for_timeout(1200)
        await self._dismiss_login_popups()
        await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=60000)
        if not await self.verify_auth():
            raise RuntimeError("instagram login falhou: inbox nao autenticada")
        logger.info("LOGIN done channel=%s", self.name)

    async def verify_auth(self) -> bool:
        page = self._require_page()
        logger.info("VERIFY_AUTH start channel=%s", self.name)
        try:
            await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=10000)
            await self._restore_local_storage()
            ok = await self._wait_for_any_selector(self.AUTH_SELECTORS, timeout_ms=10000)
            logger.info("VERIFY_AUTH %s channel=%s", "ok" if ok else "fail", self.name)
            return ok
        except Exception:
            logger.info("VERIFY_AUTH fail channel=%s", self.name)
            return False

    async def poll_messages(self) -> list[HuginnMessage]:
        page = self._require_page()
        await page.goto(self.INBOX_URL, wait_until="domcontentloaded", timeout=30000)
        raw = await page.evaluate(
            """
            () => {
                const out = [];
                const links = Array.from(document.querySelectorAll("a[href*='/direct/t/']"));
                for (const link of links) {
                    const href = link.getAttribute("href") || "";
                    const id = href.split("/direct/t/")[1]?.split("/")[0] || href;
                    const text = (link.innerText || "").trim();
                    if (!text) continue;
                    const sender = text.split("\\n")[0]?.trim() || "unknown";
                    const marker =
                        (link.getAttribute("aria-label") || "").toLowerCase() +
                        " " +
                        text.toLowerCase();
                    const hasUnread =
                        marker.includes("unread") ||
                        marker.includes("nova mensagem") ||
                        marker.includes("new message");
                    if (!hasUnread) continue;
                    out.push({
                        id,
                        sender,
                        text,
                    });
                }
                return out;
            }
            """
        )
        if not isinstance(raw, list):
            return []

        messages: list[HuginnMessage] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            thread_id = str(item.get("id", "")).strip()
            sender = str(item.get("sender", "")).strip() or "unknown"
            text = str(item.get("text", "")).strip()
            if not thread_id:
                thread_id = f"{sender}:{text[:80]}"
            if not self._mark_seen(f"ig_raw:{thread_id}"):
                continue
            content = text or f"Nova mensagem Instagram de {sender}"
            messages.append(
                HuginnMessage(
                    channel=self.name,
                    sender=sender,
                    text=content,
                    session_id=f"{self.name}-{thread_id}",
                    metadata={
                        "thread_id": thread_id,
                        "message_id": thread_id,
                        "recipient": sender,
                    },
                )
            )
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
            raise RuntimeError(f"instagram thread nao encontrada para recipient={recipient}")

        await page.wait_for_selector(self.COMPOSE_SELECTOR, timeout=15000)
        await page.click(self.COMPOSE_SELECTOR)
        await page.keyboard.type(text)
        await page.keyboard.press("Enter")
