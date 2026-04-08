from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

HuginnMode = Literal["claude_orchestrator", "deepseek_orchestrator"]


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_int(value: str | None, *, default: int) -> int:
    try:
        if value is None or value.strip() == "":
            return default
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: str | None, *, default: float) -> float:
    try:
        if value is None or value.strip() == "":
            return default
        return float(value.strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ModelPricing:
    input_per_million_usd: float
    output_per_million_usd: float

    def estimate_cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            (max(prompt_tokens, 0) / 1_000_000.0) * max(self.input_per_million_usd, 0.0)
            + (max(completion_tokens, 0) / 1_000_000.0) * max(self.output_per_million_usd, 0.0)
        )


@dataclass(frozen=True)
class HuginnSettings:
    huginn_mode: HuginnMode

    # Flags/core loop
    llm_boost_enabled: bool
    llm_validate_enabled: bool
    max_iterations: int
    exec_timeout_seconds: int
    max_subagents: int
    subagent_max_iter: int

    # API keys and model selection by role
    deepseek_api_key: str
    deepseek_api_key_exec: str
    deepseek_api_key_reason: str
    deepseek_base_url: str
    deepseek_model_exec: str
    deepseek_model_reason: str

    anthropic_api_key: str
    anthropic_api_key_orch: str
    anthropic_api_key_boost: str
    claude_model_orch: str
    claude_model_boost: str

    # Browser tooling
    browser_tools_enabled: bool
    browser_headless: bool

    # Channels
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    huginn_auth_keyword: str
    whatsapp_enabled: bool
    whatsapp_allowed_sender: str
    whatsapp_session_dir: str
    instagram_enabled: bool
    instagram_username: str
    instagram_password: str
    instagram_session_dir: str

    # Server
    huginn_host: str
    huginn_port: int
    huginn_webhook_base: str

    # Logging
    log_dir: str
    log_tokens: bool
    verbose: bool

    # Model pricing
    pricing_claude_orch: ModelPricing
    pricing_claude_boost: ModelPricing
    pricing_deepseek_exec: ModelPricing
    pricing_deepseek_reason: ModelPricing

    def get_model_pricing(self, model: str) -> ModelPricing | None:
        normalized = (model or "").strip()
        price_map = {
            self.claude_model_orch: self.pricing_claude_orch,
            self.claude_model_boost: self.pricing_claude_boost,
            self.deepseek_model_exec: self.pricing_deepseek_exec,
            self.deepseek_model_reason: self.pricing_deepseek_reason,
        }
        return price_map.get(normalized)


def _require_mode(mode: str) -> HuginnMode:
    normalized = (mode or "").strip().lower()
    if normalized in {"claude_orchestrator", "deepseek_orchestrator"}:
        return normalized  # type: ignore[return-value]
    raise ValueError(
        "HUGINN_MODE invalido. Use 'claude_orchestrator' ou 'deepseek_orchestrator'."
    )


@lru_cache(maxsize=1)
def get_settings() -> HuginnSettings:
    return HuginnSettings(
        huginn_mode=_require_mode(os.getenv("HUGINN_MODE", "claude_orchestrator")),
        llm_boost_enabled=_as_bool(os.getenv("LLM_BOOST_ENABLED"), default=False),
        llm_validate_enabled=_as_bool(os.getenv("LLM_VALIDATE_ENABLED"), default=False),
        max_iterations=max(1, _as_int(os.getenv("MAX_ITERATIONS"), default=30)),
        exec_timeout_seconds=max(5, _as_int(os.getenv("EXEC_TIMEOUT"), default=30)),
        max_subagents=max(1, _as_int(os.getenv("MAX_SUBAGENTS"), default=3)),
        subagent_max_iter=max(1, _as_int(os.getenv("SUBAGENT_MAX_ITER"), default=8)),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_api_key_exec=os.getenv("DEEPSEEK_API_KEY_EXEC", "").strip(),
        deepseek_api_key_reason=os.getenv("DEEPSEEK_API_KEY_REASON", "").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()
        or "https://api.deepseek.com/v1",
        deepseek_model_exec=os.getenv("DEEPSEEK_MODEL_EXEC", "deepseek-chat").strip()
        or "deepseek-chat",
        deepseek_model_reason=os.getenv("DEEPSEEK_MODEL_REASON", "deepseek-reasoner").strip()
        or "deepseek-reasoner",
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_api_key_orch=os.getenv("ANTHROPIC_API_KEY_ORCH", "").strip(),
        anthropic_api_key_boost=os.getenv("ANTHROPIC_API_KEY_BOOST", "").strip(),
        claude_model_orch=os.getenv("CLAUDE_MODEL_ORCH", "claude-sonnet-4-6").strip()
        or "claude-sonnet-4-6",
        claude_model_boost=os.getenv("CLAUDE_MODEL_BOOST", "claude-opus-4-6").strip()
        or "claude-opus-4-6",
        browser_tools_enabled=_as_bool(os.getenv("BROWSER_TOOLS"), default=True),
        browser_headless=_as_bool(os.getenv("BROWSER_HEADLESS"), default=True),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_allowed_chat_id=_as_int(os.getenv("TELEGRAM_ALLOWED_CHAT_ID"), default=0),
        huginn_auth_keyword=os.getenv("HUGINN_AUTH_KEYWORD", "wodan").strip().lower(),
        whatsapp_enabled=_as_bool(os.getenv("WHATSAPP_ENABLED"), default=False),
        whatsapp_allowed_sender=os.getenv("WHATSAPP_ALLOWED_SENDER", "").strip(),
        whatsapp_session_dir=os.getenv(
            "WHATSAPP_SESSION_DIR", "./huginn_sessions/whatsapp"
        ).strip()
        or "./huginn_sessions/whatsapp",
        instagram_enabled=_as_bool(os.getenv("INSTAGRAM_ENABLED"), default=False),
        instagram_username=os.getenv("INSTAGRAM_USERNAME", "").strip(),
        instagram_password=os.getenv("INSTAGRAM_PASSWORD", "").strip(),
        instagram_session_dir=os.getenv(
            "INSTAGRAM_SESSION_DIR", "./huginn_sessions/instagram"
        ).strip()
        or "./huginn_sessions/instagram",
        huginn_host=os.getenv("HUGINN_HOST", "0.0.0.0").strip() or "0.0.0.0",
        huginn_port=max(1, _as_int(os.getenv("HUGINN_PORT"), default=8000)),
        huginn_webhook_base=os.getenv("HUGINN_WEBHOOK_BASE", "").strip(),
        log_dir=os.getenv("LOG_DIR", "./logs").strip() or "./logs",
        log_tokens=_as_bool(os.getenv("LOG_TOKENS"), default=True),
        verbose=_as_bool(os.getenv("VERBOSE"), default=False),
        pricing_claude_orch=ModelPricing(
            input_per_million_usd=_as_float(os.getenv("PRICE_CLAUDE_ORCH_IN"), default=3.00),
            output_per_million_usd=_as_float(os.getenv("PRICE_CLAUDE_ORCH_OUT"), default=15.00),
        ),
        pricing_claude_boost=ModelPricing(
            input_per_million_usd=_as_float(os.getenv("PRICE_CLAUDE_BOOST_IN"), default=15.00),
            output_per_million_usd=_as_float(os.getenv("PRICE_CLAUDE_BOOST_OUT"), default=75.00),
        ),
        pricing_deepseek_exec=ModelPricing(
            input_per_million_usd=_as_float(os.getenv("PRICE_DEEPSEEK_EXEC_IN"), default=0.27),
            output_per_million_usd=_as_float(os.getenv("PRICE_DEEPSEEK_EXEC_OUT"), default=1.10),
        ),
        pricing_deepseek_reason=ModelPricing(
            input_per_million_usd=_as_float(os.getenv("PRICE_DEEPSEEK_REASON_IN"), default=0.55),
            output_per_million_usd=_as_float(
                os.getenv("PRICE_DEEPSEEK_REASON_OUT"), default=2.19
            ),
        ),
    )


def reload_settings() -> HuginnSettings:
    get_settings.cache_clear()
    return get_settings()
