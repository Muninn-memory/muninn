from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from huginn.agent import arun
from muninn_bridge import save_to_memory as muninn_save_to_memory

logger = logging.getLogger(__name__)

MEMORY_SAVE_LIMIT = 2000


async def run_huginn_query(
    query: str,
    *,
    save_to_memory: bool = True,
    after_search: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """
    Wrapper de compatibilidade para chamadas legadas.
    Encaminha para o novo AgentLoop.
    """
    q = (query or "").strip()
    if not q:
        return "Qual e a consulta, Mestre?"

    session_id = f"huginn-pipeline-{uuid.uuid4().hex[:10]}"
    answer = await arun(q, session_id=session_id, channel="terminal")

    if after_search is not None:
        try:
            await after_search()
        except Exception:
            logger.exception("Falha no callback after_search")

    if save_to_memory:
        try:
            await muninn_save_to_memory(
                title=f"Pesquisa: {q[:50]}",
                content=answer[:MEMORY_SAVE_LIMIT],
                tags=["huginn", "pesquisa", "web"],
            )
        except Exception:
            logger.exception("Erro ao salvar resumo na memoria do Muninn")
    return answer
