from __future__ import annotations

# -*- coding: utf-8 -*-
import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from huginn_tools import format_results, web_search
from muninn_bridge import get_memories, save_to_memory

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = int(os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "0"))
AUTH_KEYWORD = os.getenv("HUGINN_AUTH_KEYWORD", "").lower().strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id

    # Bloqueia qualquer chat não autorizado
    if chat_id != ALLOWED_CHAT_ID:
        logger.warning(f"Acesso negado: chat_id={chat_id}")
        return

    text = update.message.text.strip()
    lower = text.lower()

    # Comando /start
    if lower == "/start":
        await update.message.reply_text(
            "Huginn ativo. Corvo do pensamento a seu serviço, Mestre."
        )
        return

    # Comando /memoria — consulta memórias do Muninn
    if lower == "/memoria":
        await update.message.reply_text("Consultando memória do Muninn...")
        raw = await get_memories(limit=10)
        await update.message.reply_text(raw[:4000] if raw else "Nenhuma memória encontrada.")
        return

    # Busca com keyword de autorização
    if AUTH_KEYWORD and lower.startswith(AUTH_KEYWORD):
        query = text[len(AUTH_KEYWORD):].strip()
        if not query:
            await update.message.reply_text("Qual é a consulta, Mestre?")
            return

        await update.message.reply_text(f"Buscando: {query}...")
        results = web_search(query, max_results=5)
        formatted = format_results(results)

        # Salva resultado na memória do Muninn
        await save_to_memory(
            title=f"Pesquisa: {query[:50]}",
            content=formatted[:2000],
            tags=["huginn", "pesquisa", "web"]
        )

        await update.message.reply_text(formatted[:4000])
        return

    # Mensagem sem keyword — informa como usar
    await update.message.reply_text(
        f"Use '{AUTH_KEYWORD} [consulta]' para pesquisar, Mestre.\n"
        f"Ou /memoria para consultar o Muninn."
    )


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN nao configurado no .env")
    if not ALLOWED_CHAT_ID:
        raise ValueError("TELEGRAM_ALLOWED_CHAT_ID nao configurado no .env")
    if not AUTH_KEYWORD:
        raise ValueError("HUGINN_AUTH_KEYWORD nao configurado no .env")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    logger.info(f"Huginn iniciado. Aguardando mensagens de chat_id={ALLOWED_CHAT_ID}")
    app.run_polling()


if __name__ == "__main__":
    main()