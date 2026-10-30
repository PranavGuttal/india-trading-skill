"""Simulated broker with SQLite persistence.

Nothing here talks to Groww or any exchange. Every order and fill it creates
is marked mode='paper'. State survives restarts, and orders are keyed by the
intent id so the same intent can never create two orders.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Optional

import pandas as pd

from ..config import ChargeSchedule
from ..market_data.calendar import IST
from ..models import Order, OrderIntent, OrderStatus, Position, Quote, Side
from ..risk.costs import estimate_charges
from ..risk.manager import AccountState
from .base import BrokerAdapter, BrokerTimeout, UnsupportedOperation

FillModel = Literal["full", "partial", "reject"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id = 1), cash REAL NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
  intent_id TEXT PRIMARY KEY, broker_order_id TEXT, symbol TEXT, side TEXT, qty INTEGER,
  filled_qty INTEGER, avg_fill_price REAL, limit_price REAL, status TEXT, product TEXT,
  stop REAL, target REAL, trade_date TEXT, message TEXT, charges REAL, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS positions (
  symbol TEXT PRIMARY KEY, qty INTEGER, avg_price REAL, stop REAL, target REAL, product TEXT, opened_at TEXT,
  entry_charges REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS closed_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, qty INTEGER, entry REAL, exit REAL,
  charges REAL, pnl_net REAL, opened_at TEXT, closed_at TEXT, trade_date TEXT, reason TEXT);
"""


class PaperBroker(BrokerAdapter):
    name = "paper"
    is_live = False

    def __init__(
        self,
        db_path: str | Path,
        starting_cash: float,
        charges: ChargeSchedule,
        price_provider: Optional[Callable[[str], Quote]] = None,
        slippage_bps: float = 10.0,
        fill_model: FillModel = "full",
        clock: Callable[[], datetime] = lambda: datetime.now(IST),
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.charges = charges
        self.price_provider = price_provider
        self.slippage_bps = slippage_bps
        self.fill_model: FillModel = fill_model
        self.clock = clock
        self.fail_next_submit_with_timeout = False  # test hook
        with self._conn() as c:
            c.executescript(SCHEMA)
            if c.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0:
                c.execute("INSERT INTO account (id, cash) VALUES (1, ?)", (float(starting_cash),))

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    # ------------------------------------------------------------------ data
    def get_quote(self, symbol: str) -> Quote:
        if self.price_provider is None:
            raise UnsupportedOperation("paper broker has no price provider configured")
        return self.price_provider(symbol)

    def get_historical_bars(self, symbol: str, days: int) -> pd.DataFrame:
        raise UnsupportedOperation("paper broker does not serve history; use a market_data source")

    def get_instrument_details(self, symbol: str) -> dict:
        raise UnsupportedOperation("paper broker cannot verify instruments")

    # ------------------------------------------------------------------ state
    def cash(self) -> float:
        with self._conn() as c:
            return float(c.execute("SELECT cash FROM account WHERE id=1").fetchone()[0])

    def get_positions(self) -> list[Position]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM positions WHERE qty > 0").fetchall()
        return [
            Position(symbol=r["symbol"], qty=r["qty"], avg_price=r["avg_price"], mode="paper",
                     stop=r["stop"], target=r["target"], opened_at=datetime.fromisoformat(r["opened_at"]))
            for r in rows
        ]

    def realised_pnl(self, trade_date: str) -> float:
        with self._conn() as c:
            v = c.execute("SELECT COALESCE(SUM(pnl_net),0) FROM closed_trades WHERE trade_date=?", (trade_date,)).fetchone()[0]
        return float(v)

    def closed_trades(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM closed_trades ORDER BY id").fetchall()]

    def get_account_state(self, trade_date: str) -> AccountState:
        with self._conn() as c:
            pending = c.execute(
                "SELECT intent_id FROM orders WHERE status IN ('PENDING','SUBMITTED','PARTIALLY_FILLED','UNKNOWN')"
            ).fetchall()
            today = c.execute("SELECT intent_id FROM orders WHERE trade_date=?", (trade_date,)).fetchall()
            entries_today = c.execute(
                "SELECT COUNT(*) FROM orders WHERE trade_date=? AND side='BUY' AND filled_qty>0", (trade_date,)
            ).fetchone()[0]
        positions = self.get_positions()
        return AccountState(
            cash_available=self.cash(),
            open_positions=len(positions),
            pending_orders=len(pending),
            realised_pnl_today=self.realised_pnl(trade_date),
            trades_today=int(entries_today),
            verified=True,
            source="paper",
            open_symbols={p.symbol for p in positions},
            pending_intent_ids={r[0] for r in pending} | {r[0] for r in today},
        )

    def get_order_status(self, intent_id: str) -> Optional[Order]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM orders WHERE intent_id=?", (intent_id,)).fetchone()
        return self._row_to_order(r) if r else None

    def _row_to_order(self, r: sqlite3.Row) -> Order:
        return Order(
            intent_id=r["intent_id"], broker_order_id=r["broker_order_id"], symbol=r["symbol"],
            side=Side(r["side"]), qty=r["qty"], filled_qty=r["filled_qty"], avg_fill_price=r["avg_fill_price"],
            limit_price=r["limit_price"], status=OrderStatus(r["status"]), mode="paper", message=r["message"] or "",
            created_at=datetime.fromisoformat(r["created_at"]), updated_at=datetime.fromisoformat(r["updated_at"]),
        )

    # ------------------------------------------------------------------ orders
    def place_order(self, intent: OrderIntent) -> Order:
        existing = self.get_order_status(intent.intent_id)
        if existing is not None:
            return existing  # idempotent: never a second order for the same intent
        now = self.clock().isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT INTO orders VALUES (?,?,?,?,?,0,NULL,?,?,?,?,?,?,?,0,?,?)",
                (intent.intent_id, f"PAPER-{intent.intent_id[:8]}", intent.symbol, intent.side.value, intent.qty,
                 intent.limit_price, OrderStatus.SUBMITTED.value, intent.product, intent.stop, intent.target,
                 intent.trade_date, "simulated order", now, now),
            )
        if self.fail_next_submit_with_timeout:
            self.fail_next_submit_with_timeout = False
            raise BrokerTimeout("simulated timeout after the order reached the paper broker")
        return self._simulate_fill(intent)

    def _simulate_fill(self, intent: OrderIntent) -> Order:
        quote = self.get_quote(intent.symbol)
        slip = self.slippage_bps / 10_000
        status, msg, fill_qty, price = OrderStatus.SUBMITTED, "", 0, None
        if self.fill_model == "reject":
            status, msg = OrderStatus.REJECTED, "simulated rejection"
        elif intent.side == Side.BUY:
            if quote.price > intent.limit_price:
                status, msg = OrderStatus.SUBMITTED, "limit not reached; resting"
            else:
                price = min(intent.limit_price, round(quote.price * (1 + slip), 2))
                fill_qty = intent.qty if self.fill_model == "full" else max(1, intent.qty // 2)
        else:
            if quote.price < intent.limit_price:
                status, msg = OrderStatus.SUBMITTED, "limit not reached; resting"
            else:
                price = max(intent.limit_price, round(quote.price * (1 - slip), 2))
                fill_qty = intent.qty if self.fill_model == "full" else max(1, intent.qty // 2)

        if fill_qty:
            value = fill_qty * price
            ch = estimate_charges(value, intent.side.value, intent.product, self.charges).total
            if intent.side == Side.BUY and value + ch > self.cash():
                status, msg, fill_qty, price = OrderStatus.REJECTED, "insufficient paper cash", 0, None
            else:
                status = OrderStatus.FILLED if fill_qty == intent.qty else OrderStatus.PARTIALLY_FILLED
                msg = "simulated fill (NOT a real Groww execution)"
                self._apply_fill(intent, fill_qty, price, ch)
        now = self.clock().isoformat()
        with self._conn() as c:
            c.execute(
                "UPDATE orders SET status=?, filled_qty=?, avg_fill_price=?, message=?, updated_at=? WHERE intent_id=?",
                (status.value, fill_qty, price, msg, now, intent.intent_id),
            )
        return self.get_order_status(intent.intent_id)  # type: ignore[return-value]

    def _apply_fill(self, intent: OrderIntent, qty: int, price: float, charges: float) -> None:
        now = self.clock()
        with self._conn() as c:
            c.execute("UPDATE orders SET charges=charges+? WHERE intent_id=?", (charges, intent.intent_id))
            if intent.side == Side.BUY:
                c.execute("UPDATE account SET cash=cash-? WHERE id=1", (qty * price + charges,))
                c.execute(
                    "INSERT INTO positions VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
                    "avg_price=(avg_price*qty + excluded.avg_price*excluded.qty)/(qty+excluded.qty), qty=qty+excluded.qty, "
                    "entry_charges=entry_charges+excluded.entry_charges",
                    (intent.symbol, qty, price, intent.stop, intent.target, intent.product, now.isoformat(), charges),
                )
            else:
                pos = c.execute("SELECT * FROM positions WHERE symbol=?", (intent.symbol,)).fetchone()
                if pos is None or pos["qty"] < qty:
                    raise ValueError("paper sell exceeds holding (short selling is not allowed)")
                entry_ch = float(pos["entry_charges"]) * (qty / pos["qty"])
                c.execute("UPDATE account SET cash=cash+? WHERE id=1", (qty * price - charges,))
                pnl = qty * (price - pos["avg_price"]) - charges - entry_ch
                c.execute(
                    "INSERT INTO closed_trades (symbol, qty, entry, exit, charges, pnl_net, opened_at, closed_at, trade_date, reason) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (intent.symbol, qty, pos["avg_price"], price, round(charges + entry_ch, 2),
                     round(pnl, 2), pos["opened_at"], now.isoformat(), intent.trade_date, intent.proposal_ref or "exit"),
                )
                left = pos["qty"] - qty
                if left == 0:
                    c.execute("DELETE FROM positions WHERE symbol=?", (intent.symbol,))
                else:
                    c.execute("UPDATE positions SET qty=?, entry_charges=entry_charges-? WHERE symbol=?",
                              (left, entry_ch, intent.symbol))

    def cancel_order(self, intent_id: str) -> Order:
        o = self.get_order_status(intent_id)
        if o is None:
            raise ValueError(f"no paper order {intent_id}")
        if o.status in (OrderStatus.SUBMITTED, OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
            with self._conn() as c:
                c.execute("UPDATE orders SET status='CANCELLED', updated_at=? WHERE intent_id=?",
                          (self.clock().isoformat(), intent_id))
        return self.get_order_status(intent_id)  # type: ignore[return-value]
