from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI
from telegram import Message, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from huginn_tools import format_results, web_search
from muninn_bridge import get_memories, save_to_memory

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AUTH_KEYWORD = os.getenv("HUGINN_AUTH_KEYWORD", "").lower().strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"

MAX_TELEGRAM_MESSAGE_LENGTH = 4000
MEMORY_FETCH_LIMIT = 10
MEMORY_SAVE_LIMIT = 2000
SEARCH_MAX_RESULTS = 5


def _load_allowed_chat_id() -> int:
    raw_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "0").strip()
    try:
        return int(raw_chat_id)
    except ValueError:
        logger.error("TELEGRAM_ALLOWED_CHAT_ID invalido: %r", raw_chat_id)
        return 0


ALLOWED_CHAT_ID = _load_allowed_chat_id()
_deepseek_client: OpenAI | None = None


def _get_deepseek_client() -> OpenAI | None:
    global _deepseek_client
    if not DEEPSEEK_API_KEY:
        return None
    if _deepseek_client is None:
        _deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    return _deepseek_client


def _deepseek_chat(messages: list[dict[str, str]], *, max_tokens: int) -> str | None:
    client = _get_deepseek_client()
    if client is None:
        return None

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        max_tokens=max_tokens,
    )
    if not response.choices:
        return None

    content = response.choices[0].message.content
    if not content:
        return None

    return content.strip()


async def summarize_with_deepseek(query: str, results: str) -> str:
    """Resume os resultados da busca via DeepSeek."""
    if not DEEPSEEK_API_KEY:
        return results

    messages = [
        {
            "role": "system",
            "content": (
                "Voce e Huginn, o corvo do pensamento. "
                "Resuma resultados de busca de forma direta e objetiva em portugues brasileiro. "
                "Cite as fontes ao final."
            ),
        },
        {"role": "user", "content": f"Pergunta: {query}\n\nResultados encontrados:\n{results}"},
    ]
    try:
        summary = await asyncio.to_thread(_deepseek_chat, messages, max_tokens=1024)
        if summary:
            return summary

        logger.warning("DeepSeek retornou resumo vazio; usando resultados formatados")
        return results
    except Exception:
        logger.exception("Erro ao resumir com DeepSeek")
        return results


async def translate_query(query: str) -> str:
    """Traduz a consulta para ingles."""
    if not DEEPSEEK_API_KEY:
        return query

    messages = [
        {
            "role": "system",
            "content": "Traduza a query para ingles. Responda apenas com a query traduzida, sem explicacoes.",
        },
        {"role": "user", "content": query},
    ]
    try:
        translated = await asyncio.to_thread(_deepseek_chat, messages, max_tokens=100)
        if translated:
            return translated

        logger.warning("DeepSeek retornou traducao vazia; mantendo consulta original")
        return query
    except Exception:
        logger.exception("Erro ao traduzir consulta")
        return query


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
        english_query = await translate_query(query)
        logger.info("Query traduzida: %s", english_query)

        results = await asyncio.to_thread(
            web_search,
            english_query,
            SEARCH_MAX_RESULTS,
            region="br-pt",
            timelimit="d",
        )
        formatted = format_results(results)

        await message.reply_text("Analisando resultados...")
        summary = await summarize_with_deepseek(query, formatted)

        try:
            await save_to_memory(
                title=f"Pesquisa: {query[:50]}",
                content=summary[:MEMORY_SAVE_LIMIT],
                tags=["huginn", "pesquisa", "web"],
            )
        except Exception:
            logger.exception("Erro ao salvar resumo na memoria do Muninn")

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
