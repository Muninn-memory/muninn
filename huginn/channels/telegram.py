from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from huginn.channels.base import ChannelAdapter, HuginnMessage
from huginn.config import HuginnSettings, get_settings
from huginn.tools.calendar import check_calendar, list_tasks
from huginn.tools.memory import recall_memory, save_memory, search_memory

logger = logging.getLogger("huginn.channels")

MAX_TELEGRAM_MESSAGE_LENGTH = 4000


def _clip(value: object, max_chars: int = 80) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _chunk_text(payload: str, *, size: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> list[str]:
    text = (payload or "").strip() or "(sem conteudo)"
    return [text[i : i + size] for i in range(0, len(text), size)]


class TelegramChannel(ChannelAdapter):
    def __init__(
        self,
        *,
        agent_runner: Callable[[str, str, str], Awaitable[str]],
        status_provider: Callable[[], dict[str, Any]] | None = None,
        settings: HuginnSettings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._agent_runner = agent_runner
        self._status_provider = status_provider

    @property
    def name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        # polling e webhook sao inicializados por metodos especificos
        return

    async def stop(self) -> None:
        return

    async def send_message(self, recipient: str, text: str) -> None:
        token = self._settings.telegram_bot_token
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN nao configurado")

        try:
            import httpx
        except Exception as exc:
            raise RuntimeError("httpx nao disponivel para envio Telegram") from exc

        chat_id = str(recipient).strip()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                for chunk in _chunk_text(text):
                    logger.info(
                        "SEND channel=%s recipient=%s text=%.80r",
                        self.name,
                        chat_id,
                        _clip(chunk, 80),
                    )
                    response = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                    )
                    response.raise_for_status()
        except Exception:
            logger.exception("SEND error channel=%s recipient=%s", self.name, chat_id)
            raise

    async def _reply(
        self,
        *,
        reply_func: Callable[[str], Awaitable[None]] | None,
        chat_id: str,
        text: str,
    ) -> None:
        for chunk in _chunk_text(text):
            if reply_func is not None:
                logger.info(
                    "SEND channel=%s recipient=%s text=%.80r",
                    self.name,
                    chat_id,
                    _clip(chunk, 80),
                )
                try:
                    await reply_func(chunk)
                except Exception:
                    logger.exception("SEND error channel=%s recipient=%s", self.name, chat_id)
                    raise
            else:
                await self.send_message(chat_id, chunk)

    def _help_text(self) -> str:
        keyword = self._settings.huginn_auth_keyword or "<keyword>"
        return (
            "Comandos Huginn:\n"
            "- /start\n"
            "- /ajuda\n"
            "- /status\n"
            "- /memoria\n"
            "- /muninn <consulta>\n"
            "- /agenda\n"
            "- /tarefas\n"
            "- /lembrar <texto>\n"
            f"- {keyword} <consulta>\n"
        )

    async def process_message(
        self,
        message: HuginnMessage,
        *,
        reply_func: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        settings = self._settings
        text = (message.text or "").strip()
        lower = text.lower()
        chat_id = message.sender
        session_id = message.session_id or f"telegram-{chat_id}"

        if not text:
            return ""

        logger.info(
            "RECV channel=%s sender=%s text=%.80r",
            message.channel,
            chat_id,
            _clip(text, 80),
        )

        allowed = settings.telegram_allowed_chat_id
        if allowed and str(allowed) != str(chat_id):
            logger.warning("Acesso Telegram negado para chat_id=%s", chat_id)
            return ""

        if lower == "/start":
            output = "Huginn ativo. Corvo do pensamento a seu servico, Mestre."
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower in {"/ajuda", "/help"}:
            output = self._help_text()
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower == "/status":
            payload = self._status_provider() if self._status_provider else {"status": "ok"}
            output = json.dumps(payload, ensure_ascii=False, indent=2)
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower == "/memoria":
            output = await recall_memory(limit=10)
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower == "/agenda":
            output = await check_calendar(max_results=10)
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower == "/tarefas":
            output = await list_tasks(max_results=10)
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower.startswith("/lembrar"):
            content = text[len("/lembrar") :].strip()
            if not content:
                output = "Use: /lembrar <texto>"
            else:
                output = await save_memory(
                    title=f"Lembrete: {content[:60]}",
                    content=content,
                    tags=["huginn", "lembrar"],
                    memory_type="note",
                )
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        if lower.startswith("/muninn"):
            query = text[len("/muninn") :].strip()
            if not query:
                output = "Use: /muninn <consulta>"
            else:
                output = await search_memory(query=query, limit=10)
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        keyword = settings.huginn_auth_keyword
        if keyword and lower.startswith(keyword):
            query = text[len(keyword) :].strip()
            if not query:
                output = "Qual e a consulta, Mestre?"
            else:
                result = await self._agent_runner(query, session_id, "telegram")
                output = str(result)
            await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
            return output

        output = (
            f"Use '{keyword} <consulta>' para pesquisar.\n"
            "Ou /ajuda para listar comandos."
        )
        await self._reply(reply_func=reply_func, chat_id=chat_id, text=output)
        return output

    async def process_webhook_update(self, payload: dict[str, Any]) -> str:
        message = payload.get("message") or payload.get("edited_message") or {}
        if not isinstance(message, dict):
            return ""
        chat = message.get("chat", {})
        if not isinstance(chat, dict):
            return ""
        text = message.get("text")
        if not isinstance(text, str):
            return ""
        chat_id = str(chat.get("id", "")).strip()
        huginn_message = HuginnMessage(
            channel="telegram",
            sender=chat_id,
            text=text,
            session_id=f"telegram-{chat_id}",
            metadata={"raw_update": payload},
        )
        return await self.process_message(huginn_message)

    def run_polling(self) -> None:
        if not self._settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN nao configurado")

        try:
            from telegram import Update
            from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("python-telegram-bot nao disponivel") from exc

        async def handle_message(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
            msg = update.message
            if msg is None or msg.text is None:
                return
            chat = update.effective_chat
            if chat is None:
                return

            async def _reply(text: str) -> None:
                await msg.reply_text(text)

            await self.process_message(
                HuginnMessage(
                    channel="telegram",
                    sender=str(chat.id),
                    text=msg.text,
                    session_id=f"telegram-{chat.id}",
                    metadata={"update_id": update.update_id},
                ),
                reply_func=_reply,
            )

        app = ApplicationBuilder().token(self._settings.telegram_bot_token).build()
        app.add_handler(MessageHandler(filters.TEXT, handle_message))
        logger.info("Telegram polling iniciado (allowed_chat_id=%s)", self._settings.telegram_allowed_chat_id)
        app.run_polling()


def main() -> None:
    from huginn.agent import arun

    async def _runner(task: str, session_id: str, channel: str) -> str:
        return await arun(task, session_id=session_id, channel=channel)

    channel = TelegramChannel(agent_runner=_runner)
    channel.run_polling()


if __name__ == "__main__":
    main()
