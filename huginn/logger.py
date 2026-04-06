from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from huginn.config import get_settings
from huginn.providers.base import TokenUsage

_LOCK = Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            session_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            phase TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            total_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL,
            note TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(ts)")
    conn.commit()


def _csv_headers() -> list[str]:
    return [
        "ts",
        "session_id",
        "channel",
        "phase",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "note",
    ]


@dataclass(slots=True)
class SessionUsageEntry:
    ts: str
    session_id: str
    channel: str
    phase: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    note: str = ""

    def as_csv_row(self) -> list[str]:
        return [
            self.ts,
            self.session_id,
            self.channel,
            self.phase,
            self.provider,
            self.model,
            str(self.prompt_tokens),
            str(self.completion_tokens),
            str(self.total_tokens),
            f"{self.cost_usd:.8f}",
            self.note,
        ]


class SessionLogger:
    def __init__(self, *, session_id: str, channel: str, log_dir: str | None = None) -> None:
        settings = get_settings()
        self.session_id = session_id
        self.channel = channel
        self.log_dir = Path(log_dir or settings.log_dir)
        self.csv_path = self.log_dir / "sessions.csv"
        self.db_path = self.log_dir / "sessions.db"
        self._total_cost = 0.0
        self._total_tokens = 0
        self._entries = 0

        self.log_dir.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with self.csv_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(_csv_headers())

        with sqlite3.connect(self.db_path) as conn:
            _ensure_db(conn)

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def entries(self) -> int:
        return self._entries

    def _estimate_usage_cost(self, usage: TokenUsage) -> float:
        if usage.cost_usd > 0:
            return usage.cost_usd
        pricing = get_settings().get_model_pricing(usage.model)
        if pricing is None:
            return 0.0
        return pricing.estimate_cost_usd(usage.prompt_tokens, usage.completion_tokens)

    def add_usage(self, *, phase: str, usage: TokenUsage, note: str = "") -> SessionUsageEntry:
        cost_usd = self._estimate_usage_cost(usage)
        entry = SessionUsageEntry(
            ts=_utc_now_iso(),
            session_id=self.session_id,
            channel=self.channel,
            phase=phase,
            provider=usage.provider or "",
            model=usage.model or "",
            prompt_tokens=max(int(usage.prompt_tokens), 0),
            completion_tokens=max(int(usage.completion_tokens), 0),
            total_tokens=max(int(usage.total_tokens), 0),
            cost_usd=max(float(cost_usd), 0.0),
            note=note,
        )
        self._write_entry(entry)
        self._total_cost += entry.cost_usd
        self._total_tokens += entry.total_tokens
        self._entries += 1
        return entry

    def add_event(self, *, phase: str, note: str) -> SessionUsageEntry:
        entry = SessionUsageEntry(
            ts=_utc_now_iso(),
            session_id=self.session_id,
            channel=self.channel,
            phase=phase,
            provider="",
            model="",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
            note=note,
        )
        self._write_entry(entry)
        self._entries += 1
        return entry

    def _write_entry(self, entry: SessionUsageEntry) -> None:
        with _LOCK:
            with self.csv_path.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(entry.as_csv_row())

            with sqlite3.connect(self.db_path) as conn:
                _ensure_db(conn)
                conn.execute(
                    """
                    INSERT INTO sessions (
                        ts, session_id, channel, phase, provider, model,
                        prompt_tokens, completion_tokens, total_tokens, cost_usd, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.ts,
                        entry.session_id,
                        entry.channel,
                        entry.phase,
                        entry.provider,
                        entry.model,
                        entry.prompt_tokens,
                        entry.completion_tokens,
                        entry.total_tokens,
                        entry.cost_usd,
                        entry.note,
                    ),
                )
                conn.commit()

    def session_report(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT phase, provider, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, note
                FROM sessions WHERE session_id = ? ORDER BY id ASC
                """,
                (self.session_id,),
            ).fetchall()

        return {
            "session_id": self.session_id,
            "channel": self.channel,
            "entries": [
                {
                    "phase": row[0],
                    "provider": row[1],
                    "model": row[2],
                    "prompt_tokens": row[3],
                    "completion_tokens": row[4],
                    "total_tokens": row[5],
                    "cost_usd": row[6],
                    "note": row[7],
                }
                for row in rows
            ],
            "totals": {
                "total_tokens": sum(int(row[5]) for row in rows),
                "cost_usd": float(sum(float(row[6]) for row in rows)),
            },
        }


def save_usage(
    *,
    session_id: str,
    channel: str,
    phase: str,
    usage: TokenUsage,
    note: str = "",
) -> SessionUsageEntry:
    logger = SessionLogger(session_id=session_id, channel=channel)
    return logger.add_usage(phase=phase, usage=usage, note=note)


def session_report(session_id: str, *, log_dir: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    db_path = Path(log_dir or settings.log_dir) / "sessions.db"
    if not db_path.exists():
        return {"session_id": session_id, "entries": [], "totals": {"total_tokens": 0, "cost_usd": 0.0}}

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT phase, provider, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, note
            FROM sessions WHERE session_id = ? ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()
    return {
        "session_id": session_id,
        "entries": [
            {
                "phase": row[0],
                "provider": row[1],
                "model": row[2],
                "prompt_tokens": row[3],
                "completion_tokens": row[4],
                "total_tokens": row[5],
                "cost_usd": row[6],
                "note": row[7],
            }
            for row in rows
        ],
        "totals": {
            "total_tokens": sum(int(row[5]) for row in rows),
            "cost_usd": float(sum(float(row[6]) for row in rows)),
        },
    }


def cost_summary(*, days: int = 7, log_dir: str | None = None) -> str:
    days = max(1, int(days))
    settings = get_settings()
    db_path = Path(log_dir or settings.log_dir) / "sessions.db"
    if not db_path.exists():
        return "Nenhum log de custo encontrado."

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT channel, COUNT(DISTINCT session_id), SUM(total_tokens), SUM(cost_usd)
            FROM sessions
            WHERE ts >= ?
            GROUP BY channel
            ORDER BY SUM(cost_usd) DESC
            """,
            (since_iso,),
        ).fetchall()
    if not rows:
        return f"Nenhum custo registrado nos ultimos {days} dias."

    lines = [f"Resumo de custo (ultimos {days} dias):"]
    for channel, sessions, tokens, cost in rows:
        lines.append(
            f"- {channel or 'n/a'} | sessoes={int(sessions)} | tokens={int(tokens or 0)} | usd={float(cost or 0.0):.6f}"
        )
    return "\n".join(lines)
