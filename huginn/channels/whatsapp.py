from __future__ import annotations

import logging

from huginn.channels.browser_base import SessionBrowser

logger = logging.getLogger("huginn.channels")


class WhatsAppChannel(SessionBrowser):
    """
    Adaptador inicial para WhatsApp Web.
    Polling e envio ficam centralizados aqui para evolucao futura.
    """

    def __init__(self, *, session_dir: str, alert_callback=None) -> None:
        super().__init__(name="whatsapp", session_dir=session_dir, alert_callback=alert_callback)

    async def send_message(self, recipient: str, text: str) -> None:
        logger.info(
            "SEND channel=%s recipient=%s text=%.80r",
            self.name,
            recipient,
            " ".join((text or "").split())[:80],
        )
        _ = (recipient, text)
        # Stub funcional de Fase 7.
        return
