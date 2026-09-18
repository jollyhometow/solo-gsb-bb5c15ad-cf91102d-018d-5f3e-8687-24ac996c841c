"""SQLite persistence for check results (stdlib sqlite3, no external services)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import summarize
from .models import CheckResult, CheckSummary, Diagnostic

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    file_count       INTEGER NOT NULL,
    diagnostic_count INTEGER NOT NULL,
    summary          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnostics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id    TEXT NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,
    source_file TEXT NOT NULL,
    line        INTEGER NOT NULL,
    link        TEXT NOT NULL,
    target_file TEXT,
    message     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnostics_check_id ON diagnostics(check_id);
"""


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def save(self, files: dict[str, str], diagnostics: list[Diagnostic]) -> CheckResult:
        check_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        summary = summarize(diagnostics)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO checks (id, created_at, file_count, diagnostic_count, summary)"
                " VALUES (?, ?, ?, ?, ?)",
                (check_id, created_at, len(files), len(diagnostics), json.dumps(summary)),
            )
            conn.executemany(
                "INSERT INTO diagnostics"
                " (check_id, type, source_file, line, link, target_file, message)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (check_id, d.type, d.source_file, d.line, d.link, d.target_file, d.message)
                    for d in diagnostics
                ],
            )
        return CheckResult(
            check_id=check_id,
            created_at=created_at,
            file_count=len(files),
            diagnostic_count=len(diagnostics),
            summary=summary,
            diagnostics=diagnostics,
        )

    def get(self, check_id: str) -> CheckResult | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone()
            if row is None:
                return None
            diags = conn.execute(
                "SELECT type, source_file, line, link, target_file, message"
                " FROM diagnostics WHERE check_id = ? ORDER BY id",
                (check_id,),
            ).fetchall()
        return CheckResult(
            check_id=row["id"],
            created_at=row["created_at"],
            file_count=row["file_count"],
            diagnostic_count=row["diagnostic_count"],
            summary=json.loads(row["summary"]),
            diagnostics=[Diagnostic(**dict(d)) for d in diags],
        )

    def list(self, limit: int = 100) -> list[CheckSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, file_count, diagnostic_count"
                " FROM checks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            CheckSummary(
                check_id=r["id"],
                created_at=r["created_at"],
                file_count=r["file_count"],
                diagnostic_count=r["diagnostic_count"],
            )
            for r in rows
        ]
