from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Message, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from huginn_pipeline import run_huginn_query
from muninn_bridge import get_memories

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AUTH_KEYWORD = os.getenv("HUGINN_AUTH_KEYWORD", "").lower().strip()

MAX_TELEGRAM_MESSAGE_LENGTH = 4000
MEMORY_FETCH_LIMIT = 10


def _load_allowed_chat_id() -> int:
    raw_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "0").strip()
    try:
        return int(raw_chat_id)
    except ValueError:
        logger.error("TELEGRAM_ALLOWED_CHAT_ID invalido: %r", raw_chat_id)
        return 0


ALLOWED_CHAT_ID = _load_allowed_chat_id()


async def reply_text_chunked(message: Message, text: str) -> None:
    payload = (text or "").strip() or "(sem conteudo)"
    for start in range(0, len(payload), MAX_TELEGRAM_MESSAGE_LENGTH):
        await message.reply_text(payload[start : start + MAX_TELEGRAM_MESSAGE_LENGTH])


async def handle_message(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    chat = update.effective_chat
    if chat is None:
        logger.warning("Update sem chat efetivo")
        return

    if chat.id != ALLOWED_CHAT_ID:
        logger.warning("Acesso negado: chat_id=%s", chat.id)
        return

    text = message.text.strip()
    lower = text.lower()

    if lower == "/start":
        await message.reply_text("Huginn ativo. Corvo do pensamento a seu servico, Mestre.")
        return

    if lower == "/memoria":
        await message.reply_text("Consultando memoria do Muninn...")
        try:
            raw = await get_memories(limit=MEMORY_FETCH_LIMIT)
        except Exception:
            logger.exception("Erro ao consultar memoria do Muninn")
            await message.reply_text("Nao foi possivel consultar a memoria do Muninn agora.")
            return

        await reply_text_chunked(message, raw or "Nenhuma memoria encontrada.")
        return

    if AUTH_KEYWORD and lower.startswith(AUTH_KEYWORD):
        query = text[len(AUTH_KEYWORD) :].strip()
        if not query:
            await message.reply_text("Qual e a consulta, Mestre?")
            return

        await message.reply_text(f"Buscando: {query}...")

        async def after_search() -> None:
            await message.reply_text("Analisando resultados...")

        summary = await run_huginn_query(query, save_to_memory=True, after_search=after_search)
        await reply_text_chunked(message, summary)
        return

    await message.reply_text(
        f"Use '{AUTH_KEYWORD} [consulta]' para pesquisar, Mestre.\n"
        "Ou /memoria para consultar o Muninn."
    )


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN nao configurado no .env")
    if not ALLOWED_CHAT_ID:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_ID nao configurado ou invalido no .env")
    if not AUTH_KEYWORD:
        raise ValueError("HUGINN_AUTH_KEYWORD nao configurado no .env")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    logger.info("Huginn iniciado. Aguardando mensagens de chat_id=%s", ALLOWED_CHAT_ID)
    app.run_polling()


if __name__ == "__main__":
    main()
