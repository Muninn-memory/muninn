from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from huginn.agent import arun
from huginn.channels.base import ChannelAdapter, HuginnMessage
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
_whatsapp_task: asyncio.Task[None] | None = None
_instagram_task: asyncio.Task[None] | None = None


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
            "whatsapp": _whatsapp_channel is not None
            and _whatsapp_task is not None
            and not _whatsapp_task.done(),
            "instagram": _instagram_channel is not None
            and _instagram_task is not None
            and not _instagram_task.done(),
        },
    }


async def _agent_runner(task: str, session_id: str, channel: str) -> str:
    return await arun(task, session_id=session_id, channel=channel)


def _get_telegram_channel() -> TelegramChannel:
    global _telegram_channel
    if _telegram_channel is None:
        _telegram_channel = TelegramChannel(agent_runner=_agent_runner, status_provider=_build_status)
    return _telegram_channel


def _get_channel_adapter(channel_name: str) -> ChannelAdapter | None:
    channel = (channel_name or "").strip().lower()
    if channel == "telegram":
        return _get_telegram_channel()
    if channel == "whatsapp":
        return _whatsapp_channel
    if channel == "instagram":
        return _instagram_channel
    return None


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
            headless=settings.browser_headless,
            poll_interval=10.0,
            on_message=_handle_channel_message,
            alert_callback=_telegram_alert,
            allowed_sender=settings.whatsapp_allowed_sender,
        )
    if settings.instagram_enabled and _instagram_channel is None:
        _instagram_channel = InstagramChannel(
            session_dir=settings.instagram_session_dir,
            headless=settings.browser_headless,
            poll_interval=10.0,
            on_message=_handle_channel_message,
            alert_callback=_telegram_alert,
            username=settings.instagram_username,
            password=settings.instagram_password,
        )


async def _handle_channel_message(message: HuginnMessage) -> None:
    sid = (message.session_id or "").strip() or f"{message.channel}-{uuid.uuid4().hex[:12]}"
    channel = (message.channel or "").strip().lower() or "internal"
    sender = (message.sender or "").strip() or "unknown"
    task = (message.text or "").strip()
    if not task:
        logger.warning("[%s] CHANNEL empty message channel=%s sender=%s", sid, channel, sender)
        return

    logger.info(
        "[%s] CHANNEL start channel=%s sender=%s task=%.120r",
        sid,
        channel,
        sender,
        task,
    )
    started = time.perf_counter()
    try:
        answer = await arun(task, session_id=sid, channel=channel)
        adapter = _get_channel_adapter(channel)
        if adapter is None:
            logger.warning("[%s] CHANNEL adapter missing channel=%s", sid, channel)
            return

        recipient = str(message.metadata.get("recipient", "")).strip() or sender
        await adapter.send_message(recipient, answer)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info("[%s] CHANNEL done channel=%s elapsed=%.1fms", sid, channel, elapsed_ms)
    except Exception:
        logger.exception("[%s] CHANNEL error channel=%s sender=%s", sid, channel, sender)


async def _start_channel(
    channel_name: str,
    channel: ChannelAdapter | None,
) -> tuple[ChannelAdapter | None, asyncio.Task[None] | None]:
    if channel is None:
        return None, None
    try:
        await channel.start()
        task = asyncio.create_task(channel.run_poll_loop(), name=f"huginn-{channel_name}-poll")
        logger.info("CHANNEL startup ok channel=%s", channel_name)
        return channel, task
    except Exception:
        logger.exception("CHANNEL startup error channel=%s", channel_name)
        try:
            await channel.stop()
        except Exception:
            logger.exception("CHANNEL cleanup error channel=%s", channel_name)
        return None, None


async def _stop_channel(
    channel_name: str,
    channel: ChannelAdapter | None,
    task: asyncio.Task[None] | None,
) -> None:
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("CHANNEL poll stop error channel=%s", channel_name)
    if channel is not None:
        try:
            await channel.stop()
        except Exception:
            logger.exception("CHANNEL stop error channel=%s", channel_name)


@app.on_event("startup")
async def startup_event() -> None:
    global _whatsapp_channel, _instagram_channel, _whatsapp_task, _instagram_task
    settings = get_settings()
    if settings.browser_tools_enabled:
        logger.info("BROWSER preflight start headless=%s", settings.browser_headless)
        await preflight_browser_runtime(headless=settings.browser_headless)
        logger.info("BROWSER preflight ok")
    _init_optional_channels()
    _whatsapp_channel, _whatsapp_task = await _start_channel("whatsapp", _whatsapp_channel)
    _instagram_channel, _instagram_task = await _start_channel("instagram", _instagram_channel)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _whatsapp_channel, _instagram_channel, _whatsapp_task, _instagram_task
    await _stop_channel("whatsapp", _whatsapp_channel, _whatsapp_task)
    await _stop_channel("instagram", _instagram_channel, _instagram_task)
    _whatsapp_channel = None
    _instagram_channel = None
    _whatsapp_task = None
    _instagram_task = None


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

    adapter = _get_channel_adapter(channel)
    if adapter is not None and request.sender.strip():
        try:
            await adapter.send_message(request.sender.strip(), answer)
        except Exception:
            logger.exception("Falha ao enviar resposta para canal=%s", channel)

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
