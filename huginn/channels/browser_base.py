from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

from huginn.channels.base import ChannelAdapter, HuginnMessage

logger = logging.getLogger("huginn.channels")


def _clip(value: object, max_chars: int = 80) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


class SessionBrowser(ChannelAdapter):
    """
    Base para canais web com sessao persistente (WhatsApp/Instagram).
    """

    def __init__(
        self,
        *,
        name: str,
        session_dir: str,
        alert_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._name = name
        self._session_dir = Path(session_dir)
        self._running = False
        self._alert_callback = alert_callback

    @property
    def name(self) -> str:
        return self._name

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    async def start(self) -> None:
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info("CHANNEL start channel=%s session_dir=%s", self._name, self._session_dir)

    async def stop(self) -> None:
        self._running = False
        logger.info("CHANNEL stop channel=%s", self._name)

    async def send_message(self, recipient: str, text: str) -> None:
        # Implementacoes concretas de WA/IG devem sobrescrever.
        logger.info(
            "SEND channel=%s recipient=%s text=%.80r",
            self._name,
            recipient,
            _clip(text, 80),
        )
        _ = (recipient, text)

    async def poll_messages(self) -> list[HuginnMessage]:
        # Implementacoes concretas devem sobrescrever.
        return []

    async def notify_session_expired(self, reason: str) -> None:
        logger.warning("SESSION_EXPIRED channel=%s reason=%.120r", self._name, _clip(reason, 120))
        if self._alert_callback is not None:
            try:
                await self._alert_callback(
                    f"[{self._name}] Sessao expirada. Reautenticacao necessaria. Motivo: {reason}"
                )
            except Exception:
                logger.exception("SEND error channel=%s recipient=alert", self._name)

    async def run_poll_loop(
        self,
        *,
        on_message: Callable[[HuginnMessage], Awaitable[None]],
        interval_seconds: float = 5.0,
    ) -> None:
        self._running = True
        while self._running:
            try:
                messages = await self.poll_messages()
                for message in messages:
                    logger.info(
                        "RECV channel=%s sender=%s text=%.80r",
                        message.channel,
                        message.sender,
                        _clip(message.text, 80),
                    )
                    await on_message(message)
            except Exception as exc:
                await self.notify_session_expired(str(exc))
                await asyncio.sleep(max(interval_seconds, 1.0))
            else:
                await asyncio.sleep(max(interval_seconds, 1.0))
