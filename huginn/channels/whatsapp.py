from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable
from urllib.parse import quote_plus

from huginn.channels.base import HuginnMessage
from huginn.channels.browser_base import SessionBrowser

logger = logging.getLogger("huginn.channels")


class WhatsAppChannel(SessionBrowser):
    AUTH_SELECTORS = [
        "div[data-testid='chat-list']",
        "div[aria-label='Chat list']",
        "div[role='grid']",
    ]
    COMPOSE_SELECTOR = "footer div[contenteditable='true'], div[role='textbox'][contenteditable='true']"
    SEARCH_SELECTOR = "div[contenteditable='true'][data-tab='3'], div[role='textbox'][contenteditable='true']"

    def __init__(
        self,
        *,
        session_dir: str,
        headless: bool = True,
        poll_interval: float = 10.0,
        on_message: Callable[[HuginnMessage], Awaitable[None]] | None = None,
        alert_callback: Callable[[str], Awaitable[None]] | None = None,
        allowed_sender: str = "",
    ) -> None:
        super().__init__(
            name="whatsapp",
            base_url="https://web.whatsapp.com/",
            session_dir=session_dir,
            headless=headless,
            poll_interval=poll_interval,
            on_message=on_message,
            alert_callback=alert_callback,
        )
        self.allowed_sender = (allowed_sender or "").strip()

    @staticmethod
    def _normalize_sender(value: str) -> str:
        normalized = (value or "").strip()
        digits = re.sub(r"\D", "", normalized)
        return digits or normalized.lower()

    def _is_sender_allowed(self, sender: str) -> bool:
        if not self.allowed_sender:
            return True
        allowed = self._normalize_sender(self.allowed_sender)
        current = self._normalize_sender(sender)
        if not allowed or not current:
            return False
        if allowed.isdigit() and current.isdigit():
            return current.endswith(allowed)
        return current == allowed

    async def _auth_visible(self, timeout_ms: int) -> bool:
        return await self._wait_for_any_selector(self.AUTH_SELECTORS, timeout_ms=timeout_ms)

    async def login(self) -> None:
        page = self._require_page()
        logger.info("LOGIN start channel=%s", self.name)
        await page.goto(self.base_url, wait_until="domcontentloaded", timeout=120000)
        if await self._auth_visible(3000):
            logger.info("LOGIN done channel=%s reused_session=true", self.name)
            return

        logger.info("WhatsApp login pendente: escaneie o QR code em ate 120s.")
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if await self._auth_visible(3000):
                logger.info("LOGIN done channel=%s", self.name)
                return
            await asyncio.sleep(1.5)
        raise RuntimeError("whatsapp login timeout aguardando QR scan")

    async def verify_auth(self) -> bool:
        page = self._require_page()
        logger.info("VERIFY_AUTH start channel=%s", self.name)
        try:
            await page.goto(self.base_url, wait_until="domcontentloaded", timeout=15000)
            await self._restore_local_storage()
            ok = await self._auth_visible(15000)
            logger.info("VERIFY_AUTH %s channel=%s", "ok" if ok else "fail", self.name)
            return ok
        except Exception:
            logger.info("VERIFY_AUTH fail channel=%s", self.name)
            return False

    async def poll_messages(self) -> list[HuginnMessage]:
        page = self._require_page()
        raw = await page.evaluate(
            """
            () => {
                const rows = Array.from(
                    document.querySelectorAll("div[data-testid='cell-frame-container'], div[role='listitem']")
                );
                const out = [];
                for (const row of rows) {
                    const unread =
                        row.querySelector("[data-testid='icon-unread-count']") ||
                        row.querySelector("[aria-label*='unread']") ||
                        row.querySelector("[aria-label*='nao lida']");
                    if (!unread) continue;

                    const titleNode =
                        row.querySelector("span[title]") ||
                        row.querySelector("span[dir='auto']");
                    const sender = (titleNode?.getAttribute("title") || titleNode?.textContent || "").trim();
                    const text = (row.innerText || "").trim();
                    const id =
                        row.getAttribute("data-id") ||
                        row.getAttribute("id") ||
                        (sender ? `${sender}:${text.slice(0, 80)}` : text.slice(0, 120));

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
            message_id = str(item.get("id", "")).strip()
            sender = str(item.get("sender", "")).strip() or "unknown"
            text = str(item.get("text", "")).strip()
            if not message_id:
                message_id = f"{sender}:{text[:80]}"
            if not self._mark_seen(f"wa_raw:{message_id}"):
                continue
            if not self._is_sender_allowed(sender):
                continue
            content = text or f"Nova mensagem WhatsApp de {sender}"
            messages.append(
                HuginnMessage(
                    channel=self.name,
                    sender=sender,
                    text=content,
                    session_id=f"{self.name}-{message_id}",
                    metadata={
                        "message_id": message_id,
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
            raise RuntimeError("whatsapp recipient vazio")
        if not text:
            raise RuntimeError("whatsapp text vazio")

        phone = re.sub(r"\D", "", recipient)
        if phone:
            target = f"{self.base_url}send?phone={phone}&text={quote_plus(text)}"
            await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector(self.COMPOSE_SELECTOR, timeout=20000)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            return

        await page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector(self.SEARCH_SELECTOR, timeout=15000)
        await page.click(self.SEARCH_SELECTOR)
        await page.fill(self.SEARCH_SELECTOR, recipient)
        await page.keyboard.press("Enter")
        await page.wait_for_selector(self.COMPOSE_SELECTOR, timeout=15000)
        await page.click(self.COMPOSE_SELECTOR)
        await page.keyboard.type(text)
        await page.keyboard.press("Enter")
