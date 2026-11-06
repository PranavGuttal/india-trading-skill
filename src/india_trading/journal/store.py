"""Persistent trade journal (SQLite). Every decision is recorded, including
NO_TRADE and risk blocks. Never stores credentials, tokens or account ids."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

Mode = Literal["paper", "live", "backtest"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('paper','live','backtest')),
  kind TEXT NOT NULL,
  symbol TEXT,
  strategy TEXT,
  strategy_version TEXT,
  data_source TEXT,
  data_as_of TEXT,
  intent_id TEXT,
  summary TEXT,
  payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, mode TEXT NOT NULL,
  intent_id TEXT, hypothesis TEXT, observation TEXT
);
"""

KINDS = {
    "SIGNAL", "NO_TRADE", "RISK_APPROVED", "RISK_BLOCKED", "APPROVAL_REQUESTED",
    "APPROVED", "DECLINED", "ORDER_SUBMITTED", "ORDER_STATUS", "FILL", "EXIT",
    "ERROR", "RECOVERY", "KILL_SWITCH", "TICKET", "ALLOCATION", "BUDGET",
}

_SECRET_KEYS = re.compile(r"(token|secret|password|passwd|pin|otp|api[_-]?key|totp|auth|account[_-]?(id|no|number))", re.I)


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class Journal:
    def __init__(self, db_path: str | Path, durable: bool = True):
        """durable=False skips fsync: only for throwaway replay journals."""
        self.db_path = Path(db_path)
        self.durable = durable
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on error, and always close (Windows keeps open files locked)."""
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        if not self.durable:
            c.execute("PRAGMA synchronous=OFF")
        try:
            with c:
                yield c
        finally:
            c.close()

    def record(
        self, kind: str, mode: Mode, summary: str = "", symbol: Optional[str] = None,
        strategy: Optional[str] = None, strategy_version: Optional[str] = None,
        data_source: Optional[str] = None, data_as_of: Optional[str] = None,
        intent_id: Optional[str] = None, payload: Optional[dict] = None,
    ) -> int:
        if kind not in KINDS:
            raise ValueError(f"unknown journal event kind {kind}")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO events (ts, mode, kind, symbol, strategy, strategy_version, data_source, data_as_of, "
                "intent_id, summary, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().astimezone().isoformat(), mode, kind, symbol, strategy, strategy_version,
                 data_source, data_as_of, intent_id, summary, json.dumps(redact(payload or {}), default=str)),
            )
            return int(cur.lastrowid)

    def note(self, mode: Mode, intent_id: Optional[str], hypothesis: str = "", observation: str = "") -> None:
        with self._conn() as c:
            c.execute("INSERT INTO notes (ts, mode, intent_id, hypothesis, observation) VALUES (?,?,?,?,?)",
                      (datetime.now().astimezone().isoformat(), mode, intent_id, hypothesis, observation))

    def events(self, mode: Optional[Mode] = None, kind: Optional[str] = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM events WHERE 1=1", []
        if mode:
            q += " AND mode=?"; args.append(mode)
        if kind:
            q += " AND kind=?"; args.append(kind)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def export_csv(self, path: str | Path, mode: Optional[Mode] = None) -> int:
        rows = list(reversed(self.events(mode=mode, limit=1_000_000)))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            cols = ["id", "ts", "mode", "kind", "symbol", "strategy", "strategy_version",
                    "data_source", "data_as_of", "intent_id", "summary", "payload"]
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in cols})
        return len(rows)
