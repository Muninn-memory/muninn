from __future__ import annotations

import logging
from typing import TypedDict

from ddgs import DDGS

logger = logging.getLogger(__name__)


class WebSearchResult(TypedDict, total=False):
    title: str
    url: str
    snippet: str
    error: str


def web_search(
    query: str,
    max_results: int = 5,
    *,
    region: str | None = None,
    safesearch: str | None = None,
    timelimit: str | None = None,
) -> list[WebSearchResult]:
    """
    Busca no DuckDuckGo e retorna lista de resultados.

    Os campos retornados são:
    - title: título do resultado
    - url: URL do resultado
    - snippet: pequeno resumo do conteúdo
    - error: mensagem de erro em caso de falha
    """
    try:
        search_kwargs: dict[str, object] = {"max_results": max_results}
        if region is not None:
            search_kwargs["region"] = region
        if safesearch is not None:
            search_kwargs["safesearch"] = safesearch
        if timelimit is not None:
            search_kwargs["timelimit"] = timelimit

        with DDGS() as ddgs:
            results = list(ddgs.text(query, **search_kwargs))

        formatted_results: list[WebSearchResult] = []
        for r in results:
            formatted_results.append(
                WebSearchResult(
                    title=str(r.get("title", "")).strip(),
                    url=str(r.get("href", "")).strip(),
                    snippet=str(r.get("body", "")).strip(),
                )
            )
        return formatted_results
    except Exception:
        # Mantém o contrato de retornar sempre uma lista
        logger.exception("Erro ao executar web_search(query=%r, max_results=%r)", query, max_results)
        return [WebSearchResult(error="Falha na busca no DuckDuckGo.")]


def format_results(results: list[WebSearchResult]) -> str:
    """Formata resultados para injetar no contexto do LLM."""
    if not results:
        return "Nenhum resultado encontrado."

    first = results[0]
    if "error" in first and first.get("error"):
        return f"Erro na busca: {first['error']}"

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(sem título)")
        snippet = r.get("snippet", "").strip() or "(sem resumo)"
        url = r.get("url", "(sem URL)")
        lines.append(f"{i}. {title}\n   {snippet}\n   {url}")

    return "\n\n".join(lines)