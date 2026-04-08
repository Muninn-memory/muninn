from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from huginn.config import get_settings
from huginn.logger import SessionLogger
from huginn.providers.base import ProviderConfigError
from huginn.providers.factory import get_provider
from huginn.soul import PLANNER_SYSTEM, VALIDATOR_SYSTEM, build_orchestrator_system
from huginn.tools.registry import (
    ToolRuntimeContext,
    execute_tool,
    format_tool_result,
    list_tool_specs,
)

logger = logging.getLogger("huginn.agent")

DONE_SENTINEL = "__DONE__"


def _clip(value: object, max_chars: int = 200) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


@dataclass(slots=True)
class ToolCall:
    tool: str
    args: dict[str, Any]


@dataclass(slots=True)
class ParsedOutput:
    action: str
    answer: str = ""
    tool_calls: list[ToolCall] | None = None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    payload = (text or "").strip()
    if not payload:
        return None
    if payload.startswith("```"):
        payload = payload.strip("`")
        if payload.startswith("json"):
            payload = payload[4:].strip()
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = payload.find("{")
    end = payload.rfind("}")
    if start >= 0 and end > start:
        maybe = payload[start : end + 1]
        try:
            parsed = json.loads(maybe)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def parse_orchestrator_output(text: str) -> ParsedOutput:
    raw = (text or "").strip()
    if not raw:
        return ParsedOutput(action="done", answer="Sem resposta do orquestrador.")
    if raw == DONE_SENTINEL:
        return ParsedOutput(action="done", answer="")

    obj = _extract_json_object(raw)
    if obj is None:
        return ParsedOutput(action="done", answer=raw)

    action = str(obj.get("action", "")).strip().lower()
    if action == "done":
        return ParsedOutput(action="done", answer=str(obj.get("answer", "")).strip())

    if action == "tool":
        calls: list[ToolCall] = []
        if isinstance(obj.get("tool_calls"), list):
            for item in obj["tool_calls"]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("tool", "")).strip()
                args = item.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                if name:
                    calls.append(ToolCall(tool=name, args=args))
        else:
            name = str(obj.get("tool", "")).strip()
            args = obj.get("args", {})
            if not isinstance(args, dict):
                args = {}
            if name:
                calls.append(ToolCall(tool=name, args=args))
        if calls:
            return ParsedOutput(action="tool", tool_calls=calls)

    return ParsedOutput(action="done", answer=raw)


def _parse_validator_output(text: str) -> tuple[bool, str, str]:
    payload = _extract_json_object(text or "")
    if payload is None:
        return True, "", ""
    approved = bool(payload.get("approved", True))
    reason = str(payload.get("reason", "")).strip()
    improved = str(payload.get("improved_answer", "")).strip()
    return approved, reason, improved


class AgentLoop:
    def __init__(
        self,
        *,
        session_id: str,
        channel: str,
        max_iterations: int | None = None,
        include_spawn_subagent: bool = True,
        subagent_depth: int = 0,
        session_logger: SessionLogger | None = None,
    ) -> None:
        settings = get_settings()
        self.settings = settings
        self.session_id = session_id
        self.channel = channel
        self.max_iterations = max_iterations or settings.max_iterations
        self.include_spawn_subagent = include_spawn_subagent
        self.subagent_depth = subagent_depth
        self.session_logger = session_logger or SessionLogger(session_id=session_id, channel=channel)
        self._outbound_messages: list[str] = []

    async def _send_message_from_tool(self, text: str) -> None:
        self._outbound_messages.append(text)
        logger.info(
            "[%s] SEND_MESSAGE channel=%s text=%.200r",
            self.session_id,
            self.channel,
            _clip(text, 200),
        )
        self.session_logger.add_event(phase="send_message", note=text[:200])

    async def _spawn_subagent(self, task: str, context: dict[str, Any] | None = None) -> str:
        logger.info(
            "[%s] SUBAGENT start depth=%d task=%.160r",
            self.session_id,
            self.subagent_depth,
            _clip(task, 160),
        )
        if self.subagent_depth >= 2:
            return "spawn_subagent bloqueado: profundidade maxima atingida."
        if not self.include_spawn_subagent:
            return "subagents not yet implemented"

        tasks: list[str] = []
        if context and isinstance(context.get("tasks"), list):
            tasks = [str(item).strip() for item in context["tasks"] if str(item).strip()]
        if not tasks:
            tasks = [task]

        tasks = tasks[: self.settings.max_subagents]

        async def _run_one(index: int, subtask: str) -> dict[str, str]:
            sub_loop = AgentLoop(
                session_id=self.session_id,
                channel=self.channel,
                max_iterations=min(self.settings.subagent_max_iter, self.max_iterations),
                include_spawn_subagent=False,
                subagent_depth=self.subagent_depth + 1,
                session_logger=self.session_logger,
            )
            result = await sub_loop.run(subtask)
            return {"subagent": str(index), "task": subtask, "result": result}

        gathered = await asyncio.gather(
            *(_run_one(i + 1, t) for i, t in enumerate(tasks)),
            return_exceptions=True,
        )
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(gathered, start=1):
            if isinstance(item, Exception):
                normalized.append({"subagent": str(index), "task": tasks[index - 1], "result": str(item)})
            else:
                normalized.append(item)
        logger.info("[%s] SUBAGENT done count=%d", self.session_id, len(normalized))
        return json.dumps(normalized, ensure_ascii=False)

    async def _run_boost(self, task: str) -> str:
        logger.info("[%s] BOOST start", self.session_id)
        started = time.perf_counter()
        provider = get_provider("boost")
        response = await provider.complete(
            system_prompt=PLANNER_SYSTEM,
            messages=[{"role": "user", "content": task}],
            max_tokens=800,
            temperature=0.1,
        )
        self.session_logger.add_usage(phase="boost", usage=response.usage)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "[%s] BOOST done elapsed=%.1fms out=%.200r",
            self.session_id,
            elapsed_ms,
            _clip(response.text, 200),
        )
        planned = response.text.strip()
        if not planned:
            return task
        return f"Tarefa original:\n{task}\n\nPlano boost:\n{planned}"

    async def _run_validation(self, task: str, answer: str) -> tuple[bool, str, str]:
        logger.info("[%s] VALIDATE start", self.session_id)
        started = time.perf_counter()
        provider = get_provider("validator")
        response = await provider.complete(
            system_prompt=VALIDATOR_SYSTEM,
            messages=[
                {"role": "user", "content": f"TASK:\n{task}\n\nRESULTADO:\n{answer}"},
            ],
            max_tokens=700,
            temperature=0.0,
        )
        self.session_logger.add_usage(phase="validate", usage=response.usage)
        approved, reason, improved = _parse_validator_output(response.text)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "[%s] VALIDATE done approved=%s elapsed=%.1fms reason=%.160r",
            self.session_id,
            approved,
            elapsed_ms,
            _clip(reason, 160),
        )
        return approved, reason, improved

    async def _run_exec_loop(self, task: str) -> str:
        logger.info(
            "[%s] LOOP start channel=%s max_iter=%d",
            self.session_id,
            self.channel,
            self.max_iterations,
        )
        provider = get_provider("orchestrator")
        messages: list[dict[str, str]] = [{"role": "user", "content": task}]
        tool_specs = list_tool_specs(include_spawn_subagent=self.include_spawn_subagent)
        system_prompt = build_orchestrator_system(
            tool_specs=tool_specs,
            mode=self.settings.huginn_mode,
            allow_spawn_subagent=self.include_spawn_subagent,
        )
        context = ToolRuntimeContext(
            session_id=self.session_id,
            channel=self.channel,
            send_message=self._send_message_from_tool,
            spawn_subagent=self._spawn_subagent if self.include_spawn_subagent else None,
        )

        for iteration in range(1, self.max_iterations + 1):
            response = await provider.complete(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=1200,
                temperature=0.1,
            )
            self.session_logger.add_usage(phase="loop", usage=response.usage, note=f"iter={iteration}")
            parsed = parse_orchestrator_output(response.text)

            if parsed.action == "done":
                answer = parsed.answer.strip() or response.text.strip()
                if self._outbound_messages:
                    answer = f"{answer}\n\nMensagens enviadas:\n" + "\n".join(self._outbound_messages)
                logger.info(
                    "[%s] DONE iter=%d result=%.200r",
                    self.session_id,
                    iteration,
                    _clip(answer, 200),
                )
                return answer or "Concluido."

            if parsed.action != "tool" or not parsed.tool_calls:
                fallback = response.text.strip() or "Nao foi possivel concluir a tarefa."
                logger.warning(
                    "[%s] LOOP unexpected_output iter=%d fallback=%.200r",
                    self.session_id,
                    iteration,
                    _clip(fallback, 200),
                )
                return fallback

            messages.append({"role": "assistant", "content": response.text})
            for tool_call in parsed.tool_calls:
                logger.info(
                    "[%s] TOOL iter=%d name=%s args=%.200r",
                    self.session_id,
                    iteration,
                    tool_call.tool,
                    _clip(tool_call.args, 200),
                )
                result = await execute_tool(
                    tool_call.tool,
                    tool_call.args,
                    context=context,
                    include_spawn_subagent=self.include_spawn_subagent,
                )
                logger.info(
                    "[%s] TOOL result iter=%d name=%s result=%.200r",
                    self.session_id,
                    iteration,
                    tool_call.tool,
                    _clip(result, 200),
                )
                result_text = format_tool_result(result)
                messages.append({"role": "tool", "content": result_text})
                note = f"{tool_call.tool} -> {'ok' if result.get('ok') else 'erro'}"
                self.session_logger.add_event(phase="tool", note=note)

        logger.warning(
            "[%s] MAX_ITER reached after %d iterations",
            self.session_id,
            self.max_iterations,
        )
        return "Limite de iteracoes atingido sem conclusao."

    async def run(self, task: str) -> str:
        task = (task or "").strip()
        if not task:
            return "Qual e a consulta, Mestre?"
        started = time.perf_counter()
        logger.info(
            "[%s] START task=%.120r channel=%s mode=%s",
            self.session_id,
            _clip(task, 120),
            self.channel,
            self.settings.huginn_mode,
        )
        self.session_logger.add_event(phase="start", note=task[:250])

        working_task = task
        try:
            if self.settings.llm_boost_enabled:
                working_task = await self._run_boost(task)
            answer = await self._run_exec_loop(working_task)

            if self.settings.llm_validate_enabled:
                approved, reason, improved = await self._run_validation(task, answer)
                if not approved:
                    logger.info(
                        "[%s] VALIDATE_RETRY reason=%.200r",
                        self.session_id,
                        _clip(reason, 200),
                    )
                    self.session_logger.add_event(phase="validate_retry", note=reason[:250])
                    retry_task = f"{working_task}\n\nFeedback do validador:\n{reason}"
                    answer = await self._run_exec_loop(retry_task)
                elif improved:
                    answer = improved

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "[%s] FINISH elapsed=%.1fms tokens=%d cost=%.8f",
                self.session_id,
                elapsed_ms,
                self.session_logger.total_tokens,
                self.session_logger.total_cost_usd,
            )
            self.session_logger.add_event(
                phase="finish",
                note=f"cost_usd={self.session_logger.total_cost_usd:.8f}; tokens={self.session_logger.total_tokens}",
            )
            return answer
        except ProviderConfigError as exc:
            logger.exception("[%s] UNHANDLED exception in agent loop", self.session_id)
            self.session_logger.add_event(phase="error", note=f"provider_config_error: {exc}")
            return f"Erro de configuracao do Huginn: {exc}"
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("[%s] UNHANDLED exception in agent loop", self.session_id)
            self.session_logger.add_event(phase="error", note=str(exc))
            return "Falha interna no Huginn durante a execucao da tarefa."


async def arun(task: str, *, session_id: str | None = None, channel: str = "internal") -> str:
    sid = (session_id or "").strip() or f"{channel}-{uuid.uuid4().hex[:12]}"
    agent = AgentLoop(session_id=sid, channel=channel)
    return await agent.run(task)


def run(task: str, *, session_id: str | None = None, channel: str = "internal") -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(arun(task, session_id=session_id, channel=channel))
    raise RuntimeError("run() nao pode ser chamado dentro de loop async ativo. Use arun().")
