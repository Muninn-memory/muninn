from __future__ import annotations

import asyncio
import logging
from typing import TypedDict

from ddgs import DDGS

logger = logging.getLogger(__name__)

MAX_SNIPPET_LENGTH = 500
MAX_ALLOWED_RESULTS = 10


class WebSearchResult(TypedDict, total=False):
    title: str
    url: str
    snippet: str
    error: str


def _normalize_text(value: object, fallback: str = "") -> str:
    compact = " ".join(str(value or "").split())
    return compact or fallback


def web_search(
    query: str,
    max_results: int = 5,
    *,
    region: str | None = None,
    safesearch: str | None = None,
    timelimit: str | None = None,
) -> list[WebSearchResult]:
    normalized_query = _normalize_text(query)
    if not normalized_query or max_results <= 0:
        return []

    limit = min(max_results, MAX_ALLOWED_RESULTS)
    try:
        search_kwargs: dict[str, object] = {"max_results": limit}
        if region is not None:
            search_kwargs["region"] = region
        if safesearch is not None:
            search_kwargs["safesearch"] = safesearch
        if timelimit is not None:
            search_kwargs["timelimit"] = timelimit

        with DDGS() as ddgs:
            results = list(ddgs.text(normalized_query, **search_kwargs))

        formatted_results: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        for result in results:
            url = _normalize_text(result.get("href"))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            formatted_results.append(
                WebSearchResult(
                    title=_normalize_text(result.get("title"), "(sem titulo)"),
                    url=url,
                    snippet=_normalize_text(result.get("body"), "(sem resumo)")[:MAX_SNIPPET_LENGTH],
                )
            )
        return formatted_results
    except Exception:
        logger.exception("Erro ao executar web_search(query=%r, max_results=%r)", normalized_query, limit)
        return [WebSearchResult(error="Falha na busca no DuckDuckGo.")]


def format_results(results: list[WebSearchResult]) -> str:
    if not results:
        return "Nenhum resultado encontrado."

    valid_results = [result for result in results if not result.get("error")]
    if not valid_results:
        first_error = next((result.get("error") for result in results if result.get("error")), None)
        return f"Erro na busca: {first_error or 'Falha desconhecida na busca.'}"

    lines: list[str] = []
    for i, result in enumerate(valid_results, 1):
        title = result.get("title", "(sem titulo)")
        snippet = result.get("snippet", "").strip() or "(sem resumo)"
        url = result.get("url", "(sem URL)")
        lines.append(f"{i}. {title}\n   {snippet}\n   {url}")
    return "\n\n".join(lines)


async def web_search_tool(
    *,
    query: str,
    max_results: int = 5,
    region: str = "br-pt",
    timelimit: str = "d",
) -> str:
    results = await asyncio.to_thread(
        web_search,
        query,
        max_results,
        region=region,
        timelimit=timelimit,
    )
    return format_results(results)
