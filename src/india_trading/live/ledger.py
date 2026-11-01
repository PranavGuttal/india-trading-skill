"""Live order ledger (state/live.db): tickets, approvals, sends and fills.

Live orders are placed by Claude through the Groww MCP connector, not by this
process. The ledger is the record the guard hook checks before letting an
order tool call through: a ticket must be PREPARED by `live prepare`,
APPROVED by an explicit per-order yes, unexpired, and it can be SENT once.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

from ..config import Settings
from ..execution.executor import Approval
from ..models import OrderIntent
from ..risk.costs import estimate_charges
from ..risk.manager import AccountState, pnl_history_stats

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  intent_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, qty INTEGER, limit_price REAL, stop REAL, target REAL,
  product TEXT, trade_date TEXT, kind TEXT, status TEXT, created_at TEXT, approved_at TEXT, sent_at TEXT,
  reply TEXT, broker_order_id TEXT, filled_qty INTEGER DEFAULT 0, avg_price REAL, note TEXT);
"""
OPEN_STATES = ("PREPARED", "APPROVED", "SENT", "UNKNOWN")


class LedgerError(RuntimeError):
    pass


class LiveLedger:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path, isolation_level="IMMEDIATE")
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    # ------------------------------------------------------------------ tickets
    def prepare(self, intent: OrderIntent, kind: str, now: datetime) -> dict:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO tickets (intent_id, symbol, side, qty, limit_price, stop, target, product, "
                "trade_date, kind, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'PREPARED', ?)",
                (intent.intent_id, intent.symbol, intent.side.value, intent.qty, round(intent.limit_price, 2),
                 intent.stop, intent.target, intent.product, intent.trade_date, kind, now.isoformat()))
        return self.get(intent.intent_id)  # type: ignore[return-value]

    def get(self, intent_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM tickets WHERE intent_id=?", (intent_id,)).fetchone()
        return dict(r) if r else None

    def tickets(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (limit,))]

    def approve(self, intent_id: str, reply: str, now: datetime) -> dict:
        t = self.get(intent_id)
        if t is None:
            raise LedgerError(f"no live ticket {intent_id}")
        if t["status"] != "PREPARED":
            raise LedgerError(f"ticket is {t['status']}, not PREPARED")
        if not Approval(intent_id, reply).is_explicit_yes():
            raise LedgerError("approval must be an explicit 'yes' for this one order")
        with self._conn() as c:
            c.execute("UPDATE tickets SET status='APPROVED', approved_at=?, reply=? WHERE intent_id=? AND status='PREPARED'",
                      (now.isoformat(), reply[:60], intent_id))
        return self.get(intent_id)  # type: ignore[return-value]

    def consume(self, symbol: str, side: str, qty: int, price: Optional[float], now: datetime,
                ttl_seconds: int) -> tuple[Optional[dict], str]:
        """Atomically mark the ONE approved, unexpired ticket matching this exact
        order as SENT. Returns (ticket, "") or (None, why)."""
        if price is None:
            return None, "order has no limit price; only limit orders from an approved ticket are allowed"
        with self._conn() as c:
            rows = c.execute("SELECT * FROM tickets WHERE status='APPROVED' AND symbol=? AND side=?",
                             (symbol.upper(), side.upper())).fetchall()
            for r in rows:
                if datetime.fromisoformat(r["approved_at"]) + timedelta(seconds=ttl_seconds) < now:
                    c.execute("UPDATE tickets SET status='EXPIRED' WHERE intent_id=?", (r["intent_id"],))
                    continue
                if r["qty"] == int(qty) and abs(r["limit_price"] - float(price)) < 0.005:
                    c.execute("UPDATE tickets SET status='SENT', sent_at=? WHERE intent_id=? AND status='APPROVED'",
                              (now.isoformat(), r["intent_id"]))
                    return dict(r) | {"status": "SENT"}, ""
        return None, (f"no approved, unexpired live ticket for {side} {qty} {symbol} @ ₹{price}; "
                      "run `live prepare`, show the ticket, get an explicit yes, `live approve`, then send exactly it")

    def record(self, intent_id: str, status: str, broker_order_id: Optional[str], filled_qty: int,
               avg_price: Optional[float], note: str = "") -> dict:
        t = self.get(intent_id)
        if t is None or t["status"] not in ("SENT", "UNKNOWN", "PARTIALLY_FILLED"):
            raise LedgerError("only a SENT/UNKNOWN/PARTIALLY_FILLED ticket can be updated with a broker result")
        if status not in ("FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELLED", "UNKNOWN"):
            raise LedgerError(f"bad status {status}")
        if filled_qty < 0 or filled_qty > t["qty"]:
            raise LedgerError("filled quantity outside the ticket quantity")
        with self._conn() as c:
            c.execute("UPDATE tickets SET status=?, broker_order_id=?, filled_qty=?, avg_price=?, note=? WHERE intent_id=?",
                      (status, broker_order_id, filled_qty, avg_price, note[:200], intent_id))
        return self.get(intent_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------ positions / account
    def positions(self) -> dict[str, dict]:
        """Average-cost positions from filled tickets, in time order."""
        pos: dict[str, dict] = {}
        for t in sorted(self._filled(), key=lambda r: r["created_at"]):
            p = pos.setdefault(t["symbol"], {"qty": 0, "avg": 0.0, "stop": None, "target": None})
            if t["side"] == "BUY":
                total = p["qty"] + t["filled_qty"]
                p["avg"] = (p["avg"] * p["qty"] + t["avg_price"] * t["filled_qty"]) / total
                p["qty"], p["stop"], p["target"] = total, t["stop"], t["target"]
            else:
                p["qty"] -= t["filled_qty"]
        return {s: p for s, p in pos.items() if p["qty"] > 0}

    def closed(self, settings: Settings) -> list[tuple[str, float]]:
        """(trade_date, estimated net P&L) per filled SELL, using average cost and the charge model."""
        out, cost = [], {}
        for t in sorted(self._filled(), key=lambda r: r["created_at"]):
            q, avg = cost.get(t["symbol"], (0, 0.0))
            value = t["filled_qty"] * t["avg_price"]
            if t["side"] == "BUY":
                cost[t["symbol"]] = (q + t["filled_qty"], (avg * q + value) / (q + t["filled_qty"]))
            else:
                buy_ch = estimate_charges(t["filled_qty"] * avg, "BUY", t["product"], settings.charges).total
                sell_ch = estimate_charges(value, "SELL", t["product"], settings.charges).total
                out.append((t["trade_date"], round(t["filled_qty"] * (t["avg_price"] - avg) - buy_ch - sell_ch, 2)))
                cost[t["symbol"]] = (q - t["filled_qty"], avg)
        return out

    def _filled(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM tickets WHERE filled_qty > 0 AND avg_price IS NOT NULL")]

    def account_state(self, settings: Settings, trade_date: str, broker_cash: Optional[float]) -> AccountState:
        """Fails closed (verified=False) without a cash figure read from Groww."""
        pos = self.positions()
        deployed = sum(p["qty"] * p["avg"] for p in pos.values())
        open_tickets = [t for t in self.tickets(1000) if t["status"] in OPEN_STATES]
        closed = self.closed(settings)
        today = [p for d, p in closed if d == trade_date]
        entries_today = sum(1 for t in self.tickets(1000)
                            if t["trade_date"] == trade_date and t["side"] == "BUY" and t["filled_qty"])
        cash = 0.0 if broker_cash is None else min(broker_cash, settings.max_experimental_allocation_inr - deployed)
        return AccountState(
            cash_available=max(0.0, cash), open_positions=len(pos), pending_orders=len(open_tickets),
            realised_pnl_today=round(sum(today), 2), trades_today=entries_today,
            verified=broker_cash is not None, source="live-ledger+groww-cash",
            open_symbols=set(pos), pending_intent_ids={t["intent_id"] for t in self.tickets(1000)
                                                       if t["trade_date"] == trade_date},
            **pnl_history_stats(closed, trade_date),
        )
