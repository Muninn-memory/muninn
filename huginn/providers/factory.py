from __future__ import annotations

from huginn.config import get_settings
from huginn.providers.base import LLMProvider, ProviderConfigError
from huginn.providers.claude import ClaudeProvider
from huginn.providers.deepseek import DeepSeekProvider


def _first_non_empty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def _build_claude(*, role: str, prefer_boost_key: bool = False) -> LLMProvider:
    settings = get_settings()
    api_key = _first_non_empty(
        settings.anthropic_api_key_boost if prefer_boost_key else "",
        settings.anthropic_api_key_orch,
        settings.anthropic_api_key,
    )
    model = settings.claude_model_boost if prefer_boost_key else settings.claude_model_orch
    if not api_key:
        raise ProviderConfigError(
            f"Nenhuma chave Anthropic disponivel para role='{role}'. Configure ANTHROPIC_API_KEY_*."
        )
    return ClaudeProvider(api_key=api_key, model=model, role=role)


def _build_deepseek(*, role: str, use_reasoner: bool = False) -> LLMProvider:
    settings = get_settings()
    api_key = _first_non_empty(
        settings.deepseek_api_key_reason if use_reasoner else "",
        settings.deepseek_api_key_exec,
        settings.deepseek_api_key,
    )
    model = settings.deepseek_model_reason if use_reasoner else settings.deepseek_model_exec
    if not api_key:
        raise ProviderConfigError(
            f"Nenhuma chave DeepSeek disponivel para role='{role}'. Configure DEEPSEEK_API_KEY_*."
        )
    return DeepSeekProvider(
        api_key=api_key,
        model=model,
        base_url=settings.deepseek_base_url,
        role=role,
    )


def get_provider(role: str) -> LLMProvider:
    """
    Resolve provider por papel sem fallback implícito silencioso.
    Regras:
    - orchestrator: depende de HUGINN_MODE
    - boost/validator: Claude boost
    - exec: DeepSeek chat
    - reasoner: DeepSeek reasoner
    """
    normalized = (role or "").strip().lower()
    settings = get_settings()

    if normalized == "orchestrator":
        if settings.huginn_mode == "claude_orchestrator":
            return _build_claude(role=normalized, prefer_boost_key=False)
        return _build_deepseek(role=normalized, use_reasoner=False)

    if normalized in {"boost", "validator"}:
        return _build_claude(role=normalized, prefer_boost_key=True)

    if normalized == "exec":
        return _build_deepseek(role=normalized, use_reasoner=False)

    if normalized == "reasoner":
        return _build_deepseek(role=normalized, use_reasoner=True)

    raise ProviderConfigError(f"Role de provider desconhecida: {role!r}")
