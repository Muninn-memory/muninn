from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from huginn.tools.browser import browser_navigate, browser_result_to_text
from huginn.tools.calendar import check_calendar, create_event
from huginn.tools.deep_think import deep_think
from huginn.tools.memory import recall_memory, save_memory, search_memory
from huginn.tools.web_search import web_search_tool

logger = logging.getLogger("huginn.tools")

ToolHandler = Callable[[dict[str, Any], "ToolRuntimeContext"], Awaitable[str]]


def _clip(value: object, max_chars: int = 200) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    handler: ToolHandler

    def as_prompt_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
        }


@dataclass(slots=True)
class ToolRuntimeContext:
    session_id: str
    channel: str
    send_message: Callable[[str], Awaitable[None]] | None = None
    spawn_subagent: Callable[[str, dict[str, Any] | None], Awaitable[str]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


async def _handle_web_search(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    return await web_search_tool(
        query=str(args.get("query", "")),
        max_results=int(args.get("max_results", 5)),
    )


async def _handle_browser_navigate(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    result = await browser_navigate(
        task=str(args.get("task", "")),
        url=str(args.get("url", "")).strip() or None,
        screenshot=bool(args.get("screenshot", False)),
    )
    return browser_result_to_text(result)


async def _handle_recall_memory(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    return await recall_memory(
        query=str(args.get("query", "")),
        limit=int(args.get("limit", 10)),
    )


async def _handle_search_memory(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    return await search_memory(
        query=str(args.get("query", "")),
        limit=int(args.get("limit", 10)),
    )


async def _handle_save_memory(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    tags = args.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return await save_memory(
        title=str(args.get("title", "")),
        content=str(args.get("content", "")),
        tags=[str(t) for t in tags],
        memory_type=str(args.get("type", "result")),
    )


async def _handle_check_calendar(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    return await check_calendar(max_results=int(args.get("max_results", 10)))


async def _handle_create_event(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    guests = args.get("guests", [])
    if not isinstance(guests, list):
        guests = []
    return await create_event(
        title=str(args.get("title", "")),
        start=str(args.get("start", "")),
        end=str(args.get("end", "")).strip() or None,
        description=str(args.get("description", "")),
        location=str(args.get("location", "")),
        guests=[str(g) for g in guests],
    )


async def _handle_send_message(args: dict[str, Any], context: ToolRuntimeContext) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        return "send_message: campo 'text' vazio."
    if context.send_message is None:
        return "send_message: callback indisponivel no contexto."
    await context.send_message(text)
    return "Mensagem enviada."


async def _handle_deep_think(args: dict[str, Any], _context: ToolRuntimeContext) -> str:
    return await deep_think(question=str(args.get("question", "")))


async def _handle_spawn_subagent(args: dict[str, Any], context: ToolRuntimeContext) -> str:
    task = str(args.get("task", "")).strip()
    if not task:
        return "spawn_subagent: campo 'task' vazio."
    if context.spawn_subagent is None:
        return "subagents not yet implemented"
    extra = args.get("context")
    if not isinstance(extra, dict):
        extra = None
    return await context.spawn_subagent(task, extra)


TOOLS: dict[str, ToolSpec] = {
    "web_search": ToolSpec(
        name="web_search",
        description="Busca na web e retorna resultados formatados.",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"],
        },
        handler=_handle_web_search,
    ),
    "browser_navigate": ToolSpec(
        name="browser_navigate",
        description="Navega no browser efemero e extrai conteudo.",
        schema={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "url": {"type": "string"},
                "screenshot": {"type": "boolean"},
            },
            "required": ["task"],
        },
        handler=_handle_browser_navigate,
    ),
    "recall_memory": ToolSpec(
        name="recall_memory",
        description="Recupera memorias por busca textual ou lista recentes.",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        },
        handler=_handle_recall_memory,
    ),
    "search_memory": ToolSpec(
        name="search_memory",
        description="Busca memoria por texto.",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        handler=_handle_search_memory,
    ),
    "save_memory": ToolSpec(
        name="save_memory",
        description="Salva memoria no Muninn MCP.",
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array"},
                "type": {"type": "string"},
            },
            "required": ["title", "content"],
        },
        handler=_handle_save_memory,
    ),
    "check_calendar": ToolSpec(
        name="check_calendar",
        description="Lista eventos proximos do calendario.",
        schema={"type": "object", "properties": {"max_results": {"type": "integer"}}},
        handler=_handle_check_calendar,
    ),
    "create_event": ToolSpec(
        name="create_event",
        description="Cria evento no calendario.",
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "guests": {"type": "array"},
            },
            "required": ["title", "start"],
        },
        handler=_handle_create_event,
    ),
    "send_message": ToolSpec(
        name="send_message",
        description="Envia mensagem para o canal de origem.",
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=_handle_send_message,
    ),
    "deep_think": ToolSpec(
        name="deep_think",
        description="Escala para modelo reasoner em questoes complexas.",
        schema={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        handler=_handle_deep_think,
    ),
    "spawn_subagent": ToolSpec(
        name="spawn_subagent",
        description="Cria subagentes para subtarefas em paralelo.",
        schema={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["task"],
        },
        handler=_handle_spawn_subagent,
    ),
}


def list_tool_specs(*, include_spawn_subagent: bool = True) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for name, spec in TOOLS.items():
        if not include_spawn_subagent and name == "spawn_subagent":
            continue
        specs.append(spec.as_prompt_dict())
    return specs


def _validate_required_fields(schema: dict[str, Any], args: dict[str, Any]) -> str | None:
    required = schema.get("required", [])
    if not isinstance(required, list):
        return None
    for field in required:
        if field not in args:
            return f"campo obrigatorio ausente: {field}"
    return None


async def execute_tool(
    name: str,
    args: dict[str, Any] | None,
    *,
    context: ToolRuntimeContext,
    include_spawn_subagent: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    tool_name = (name or "").strip()
    payload = args or {}
    logger.info(
        "TOOL execute session_id=%s channel=%s name=%s args=%.200r",
        context.session_id,
        context.channel,
        tool_name,
        _clip(payload, 200),
    )
    spec = TOOLS.get(tool_name)
    if spec is None or (tool_name == "spawn_subagent" and not include_spawn_subagent):
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.warning(
            "TOOL unknown session_id=%s channel=%s name=%s elapsed=%.1fms",
            context.session_id,
            context.channel,
            tool_name,
            elapsed_ms,
        )
        return {"ok": False, "tool": tool_name, "error": f"tool desconhecida: {tool_name}"}

    missing = _validate_required_fields(spec.schema, payload)
    if missing:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.warning(
            "TOOL invalid_args session_id=%s channel=%s name=%s error=%.200r elapsed=%.1fms",
            context.session_id,
            context.channel,
            tool_name,
            _clip(missing, 200),
            elapsed_ms,
        )
        return {"ok": False, "tool": tool_name, "error": missing}

    try:
        result = await spec.handler(payload, context)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "TOOL ok session_id=%s channel=%s name=%s elapsed=%.1fms result=%.200r",
            context.session_id,
            context.channel,
            tool_name,
            elapsed_ms,
            _clip(result, 200),
        )
        return {"ok": True, "tool": tool_name, "result": result}
    except Exception:  # pragma: no cover - safety net
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.exception(
            "TOOL error session_id=%s channel=%s name=%s elapsed=%.1fms",
            context.session_id,
            context.channel,
            tool_name,
            elapsed_ms,
        )
        return {
            "ok": False,
            "tool": tool_name,
            "error": f"[tool_error] {tool_name} falhou. Verifique os logs.",
        }


def format_tool_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
