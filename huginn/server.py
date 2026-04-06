from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from huginn.agent import arun
from huginn.channels.instagram import InstagramChannel
from huginn.channels.telegram import TelegramChannel
from huginn.channels.whatsapp import WhatsAppChannel
from huginn.config import get_settings
from huginn.logger import session_report
from huginn.logging_config import configure_logging
from huginn.tools.browser import preflight_browser_runtime

configure_logging(get_settings().log_dir)
logger = logging.getLogger("huginn.server")

app = FastAPI(title="Huginn Server", version="0.1.0")
STARTED_AT = datetime.now(timezone.utc)
_telegram_channel: TelegramChannel | None = None
_whatsapp_channel: WhatsAppChannel | None = None
_instagram_channel: InstagramChannel | None = None


class TaskRequest(BaseModel):
    task: str = Field(..., min_length=1)
    channel: str = "internal"
    sender: str = "dispatch"
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    session_id: str
    channel: str
    answer: str
    report: dict[str, Any]


@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    logger.info("[%s] -> %s %s", req_id, request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("[%s] UNHANDLED exception in request", req_id)
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "[%s] <- %s %s | status=%d | %.1fms",
        req_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


def _build_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
        "mode": settings.huginn_mode,
        "flags": {
            "boost": settings.llm_boost_enabled,
            "validate": settings.llm_validate_enabled,
            "browser_tools": settings.browser_tools_enabled,
            "whatsapp_enabled": settings.whatsapp_enabled,
            "instagram_enabled": settings.instagram_enabled,
        },
        "limits": {
            "max_iterations": settings.max_iterations,
            "max_subagents": settings.max_subagents,
            "subagent_max_iter": settings.subagent_max_iter,
        },
        "channels_runtime": {
            "telegram": _telegram_channel is not None,
            "whatsapp": _whatsapp_channel is not None,
            "instagram": _instagram_channel is not None,
        },
    }


async def _agent_runner(task: str, session_id: str, channel: str) -> str:
    return await arun(task, session_id=session_id, channel=channel)


def _get_telegram_channel() -> TelegramChannel:
    global _telegram_channel
    if _telegram_channel is None:
        _telegram_channel = TelegramChannel(agent_runner=_agent_runner, status_provider=_build_status)
    return _telegram_channel


async def _telegram_alert(message: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_allowed_chat_id:
        return
    try:
        await _get_telegram_channel().send_message(str(settings.telegram_allowed_chat_id), message)
    except Exception:
        logger.exception("Falha ao enviar alerta de canal para Telegram")


def _init_optional_channels() -> None:
    global _whatsapp_channel, _instagram_channel
    settings = get_settings()
    if settings.whatsapp_enabled and _whatsapp_channel is None:
        _whatsapp_channel = WhatsAppChannel(
            session_dir=settings.whatsapp_session_dir,
            alert_callback=_telegram_alert,
        )
    if settings.instagram_enabled and _instagram_channel is None:
        _instagram_channel = InstagramChannel(
            session_dir=settings.instagram_session_dir,
            alert_callback=_telegram_alert,
        )


@app.on_event("startup")
async def startup_event() -> None:
    settings = get_settings()
    if settings.browser_tools_enabled:
        logger.info("BROWSER preflight start headless=%s", settings.browser_headless)
        await preflight_browser_runtime(headless=settings.browser_headless)
        logger.info("BROWSER preflight ok")
    _init_optional_channels()


@app.get("/status")
async def status() -> dict[str, Any]:
    return _build_status()


@app.post("/task", response_model=TaskResponse)
async def run_task(request: TaskRequest) -> TaskResponse:
    channel = (request.channel or "internal").strip().lower()
    sid = (request.session_id or "").strip() or f"{channel}-{uuid.uuid4().hex[:12]}"
    logger.info(
        "[%s] TASK start channel=%s sender=%s task=%.120r",
        sid,
        channel,
        request.sender,
        request.task,
    )
    started = time.perf_counter()
    answer = await arun(request.task, session_id=sid, channel=channel)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    logger.info("[%s] TASK done channel=%s elapsed=%.1fms", sid, channel, elapsed_ms)

    if channel == "telegram" and request.sender.strip():
        try:
            await _get_telegram_channel().send_message(request.sender.strip(), answer)
        except Exception:
            logger.exception("Falha ao enviar resposta para Telegram")

    return TaskResponse(
        session_id=sid,
        channel=channel,
        answer=answer,
        report=session_report(sid),
    )


@app.post("/webhook/telegram")
async def telegram_webhook(update: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN nao configurado")
    response = await _get_telegram_channel().process_webhook_update(update)
    return {"ok": True, "response": response}


@app.post("/webhook/{channel_name}")
async def generic_webhook(channel_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    channel = (channel_name or "").strip().lower()
    if channel == "telegram":
        return await telegram_webhook(payload)
    return {"ok": False, "error": f"webhook nao implementado para canal '{channel}'"}
