"""Append-only audit log of every tool call (planned or applied) in SQLite.

The dashboard reads this; the agent and CLI write to it. One row per tool call.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .models import ActionResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    tool       TEXT    NOT NULL,
    summary    TEXT    NOT NULL,
    destructive INTEGER NOT NULL,
    applied    INTEGER NOT NULL,
    args       TEXT,
    output     TEXT,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""


def _connect(settings: Settings) -> sqlite3.Connection:
    path = Path(settings.audit_db).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def record(
    result: ActionResult,
    args: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    conn = _connect(settings)
    try:
        conn.execute(
            "INSERT INTO audit (ts, tool, summary, destructive, applied, args, output, error) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                result.ts,
                result.tool,
                result.summary,
                int(result.planned.destructive),
                int(result.applied),
                json.dumps(args or {}, default=str),
                json.dumps(result.output, default=str),
                result.error,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recent(limit: int = 50, settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    conn = _connect(settings)
    try:
        rows = conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["args"] = json.loads(d["args"]) if d["args"] else {}
            d["output"] = json.loads(d["output"]) if d["output"] else None
            d["destructive"] = bool(d["destructive"])
            d["applied"] = bool(d["applied"])
            out.append(d)
        return out
    finally:
        conn.close()
