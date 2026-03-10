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

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")


async def summarize_with_deepseek(query: str, results: str) -> str:
    """Resume os resultados da busca via DeepSeek."""
    from openai import OpenAI
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "VocÃª Ã© Huginn, o corvo do pensamento. Resume resultados de busca de forma direta e objetiva em portuguÃªs brasileiro. Cite as fontes ao final."},
                {"role": "user", "content": f"Pergunta: {query}\n\nResultados encontrados:\n{results}"}
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("Erro ao resumir com DeepSeek")
        return results  # fallback para resultados brutos

async def translate_query(query: str) -> str:
    """Traduz a consulta para inglÃªs."""
    from openai import OpenAI
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "Traduza a query para inglÃªs. Responda APENAS com a query traduzida, sem explicaÃ§Ãµes."},
                {"role": "user", "content": query}],
            max_tokens=100,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("Erro ao traduzir consulta")
        return query

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id

    # Bloqueia qualquer chat nÃ£o autorizado
    if chat_id != ALLOWED_CHAT_ID:
        logger.warning(f"Acesso negado: chat_id={chat_id}")
        return

    text = update.message.text.strip()
    lower = text.lower()

    # Comando /start
    if lower == "/start":
        await update.message.reply_text(
            "Huginn ativo. Corvo do pensamento a seu serviÃ§o, Mestre."
        )
        return

    # Comando /memoria â€” consulta memÃ³rias do Muninn
    if lower == "/memoria":
        await update.message.reply_text("Consultando memÃ³ria do Muninn...")
        raw = await get_memories(limit=10)
        await update.message.reply_text(raw[:4000] if raw else "Nenhuma memÃ³ria encontrada.")
        return

    # Busca com keyword de autorizaÃ§Ã£o
    if AUTH_KEYWORD and lower.startswith(AUTH_KEYWORD):
        query = text[len(AUTH_KEYWORD):].strip()
        if not query:
            await update.message.reply_text("Qual Ã© a consulta, Mestre?")
            return

        await update.message.reply_text(f"Buscando: {query}...")
        english_query = await translate_query(query)
        logger.info(f"Query traduzida: {english_query}")
        results = web_search(english_query, max_results=5, region="br-pt", timelimit="d")
        formatted = format_results(results)

        # Resumo via DeepSeek
        await update.message.reply_text("Analisando resultados...")
        summary = await summarize_with_deepseek(query, formatted)

        # Salva resumo na memÃ³ria do Muninn
        await save_to_memory(
            title=f"Pesquisa: {query[:50]}",
            content=summary[:2000],
            tags=["huginn", "pesquisa", "web"]
        )

        await update.message.reply_text(summary[:4000])
        return

    # Mensagem sem keyword â€” informa como usar
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


