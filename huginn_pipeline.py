from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from dotenv import load_dotenv
from openai import OpenAI

from huginn_tools import format_results, web_search
from muninn_bridge import save_to_memory

load_dotenv()

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"

MEMORY_SAVE_LIMIT = 2000
SEARCH_MAX_RESULTS = 5

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


async def run_huginn_query(
    query: str,
    *,
    save_to_memory: bool = True,
    after_search: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """
    Pipeline Huginn: traduz query, busca na web, resume com DeepSeek e opcionalmente grava no Muninn.
    after_search: corrotina chamada após a busca e antes do resumo (ex.: mensagem "Analisando..." no Telegram).
    Retorna texto final para o Mestre (ou mensagem de erro legível).
    """
    q = (query or "").strip()
    if not q:
        return "Qual e a consulta, Mestre?"

    english_query = await translate_query(q)
    logger.info("Query traduzida: %s", english_query)

    try:
        results = await asyncio.to_thread(
            web_search,
            english_query,
            SEARCH_MAX_RESULTS,
            region="br-pt",
            timelimit="d",
        )
    except Exception:
        logger.exception("Erro na busca web")
        return "Falha ao buscar na web. Tente de novo, Mestre."

    formatted = format_results(results)
    if after_search is not None:
        await after_search()
    summary = await summarize_with_deepseek(q, formatted)

    if save_to_memory:
        try:
            await save_to_memory(
                title=f"Pesquisa: {q[:50]}",
                content=summary[:MEMORY_SAVE_LIMIT],
                tags=["huginn", "pesquisa", "web"],
            )
        except Exception:
            logger.exception("Erro ao salvar resumo na memoria do Muninn")

    return summary
