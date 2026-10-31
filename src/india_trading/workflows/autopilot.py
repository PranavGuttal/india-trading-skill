"""Autopilot: one unattended PAPER trading tick over the watchlist.

Per tick, in this order:
  1. EXITS for open paper positions: gap through stop, stop, target,
     close < SMA50, or max hold days. Exits are never blocked by entry limits
     or the kill switch (they only reduce risk).
  2. Optional regime gate: no new entries while watchlist breadth is RISK_OFF.
  3. ENTRIES: each symbol not held goes through the normal Supervisor
     (validate -> strategy -> RiskManager -> ticket). Approval is automatic,
     and ONLY because the broker is the paper broker: this class refuses a
     live adapter outright, so it can never place a real order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..analysis.breadth import compute as compute_breadth
from ..brokers.base import BrokerAdapter
from ..config import Settings
from ..execution.executor import ExecutionRefused
from ..indicators.core import sma
from ..journal.store import Journal
from ..market_data.calendar import IST, NSECalendar
from ..market_data.csv_source import DataError, load_csv
from ..models import OrderIntent, Quote, Side
from ..strategies import ma_trend
from .supervisor import Step, Supervisor

AUTO_REPLY = "yes (auto-approved: paper autopilot)"


@dataclass
class TickReport:
    now: datetime
    exits: list[str] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)
    blocked: dict[str, list[str]] = field(default_factory=dict)
    no_trade: list[str] = field(default_factory=list)
    signals: int = 0
    regime: str = "not checked"
    notes: list[str] = field(default_factory=list)


def exit_decision(bar: tuple[float, float, float, float], stop: float, target: float, sma50: float,
                  held_days: int, max_hold_days: int) -> tuple[Optional[float], str]:
    """(exit price, reason) for one bar, or (None, "") to keep holding.
    Stop is checked before target when one bar touches both (conservative)."""
    o, h, l, c = bar
    if o <= stop:
        return o, "gap below stop"
    if l <= stop:
        return stop, "stop"
    if h >= target:
        return max(o, target), "target"
    if not np.isnan(sma50) and c < sma50:
        return c, "trend exit (close < SMA50)"
    if held_days >= max_hold_days:
        return c, "max hold"
    return None, ""


class AutoPilot:
    def __init__(self, settings: Settings, broker: BrokerAdapter, journal: Journal, calendar: NSECalendar,
                 data_dir: str | Path, max_hold_days: int = ma_trend.PARAMS.max_hold_days):
        if broker.is_live:
            raise ExecutionRefused("autopilot is paper-only; it refuses live broker adapters")
        self.s, self.broker, self.journal, self.calendar = settings, broker, journal, calendar
        self.data_dir = Path(data_dir)
        self.max_hold_days = max_hold_days
        self.supervisor = Supervisor(settings, broker, journal, calendar)
        self._quotes: dict[str, Quote] = {}
        self.sources: dict[str, str] = {}
        broker.price_provider = lambda sym: self._quotes[sym]

    def load_frames(self, as_of: Optional[date] = None) -> dict[str, pd.DataFrame]:
        frames = {}
        for sym in self.s.watchlist:
            try:
                df, rep, src = load_csv(self.data_dir / f"{sym}.csv", sym, self.calendar)
            except DataError:
                continue
            if rep.ok:
                self.sources[sym] = src
                frames[sym] = df if as_of is None else df[df["date"].dt.date <= as_of].reset_index(drop=True)
        return frames

    def _approve(self, ticket: str, intent_id: str) -> Optional[str]:
        return None if self.broker.is_live else AUTO_REPLY

    def tick(self, now: datetime, quotes: dict[str, Quote], as_of: Optional[date] = None,
             frames: Optional[dict[str, pd.DataFrame]] = None) -> TickReport:
        """quotes: current price per symbol (live read or replay close). With
        as_of set (replay), exits use that day's full OHLC bar."""
        rep = TickReport(now=now)
        today = now.astimezone(IST).date()
        frames = frames if frames is not None else self.load_frames(as_of)
        self._quotes = dict(quotes)

        # 1. exits
        for pos in self.broker.get_positions():
            df, q = frames.get(pos.symbol), quotes.get(pos.symbol)
            if df is None or df.empty or q is None:
                rep.notes.append(f"{pos.symbol}: no price this tick; position left open")
                continue
            last = df.iloc[-1]
            if as_of is not None and pd.Timestamp(last["date"]).date() == today:
                bar = (float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"]))
            else:
                bar = (q.price,) * 4
            sma50 = float(sma(df["close"], 50).iloc[-1]) if len(df) >= 50 else float("nan")
            held = int(np.busday_count(pos.opened_at.astimezone(IST).date(), today))
            px, why = exit_decision(bar, pos.stop or 0.0, pos.target or float("inf"), sma50, held, self.max_hold_days)
            if px is None:
                continue
            self._quotes[pos.symbol] = q.model_copy(update={"price": round(px, 2)})
            intent = OrderIntent(symbol=pos.symbol, side=Side.SELL, qty=pos.qty, limit_price=round(px * 0.995, 2),
                                 product=self.s.product, trade_date=str(today),
                                 proposal_ref=f"autopilot-exit:{why}:{now.isoformat()}")
            o = self.broker.place_order(intent)
            msg = f"{o.status.value} SELL {o.filled_qty} {pos.symbol} @ {o.avg_fill_price} ({why}; {q.source})"
            self.journal.record("EXIT", "paper", msg, symbol=pos.symbol, intent_id=o.intent_id,
                                payload=o.model_dump(mode="json"))
            rep.exits.append(msg)

        # 2. regime gate
        if self.s.regime_gate:
            b = compute_breadth(frames)
            rep.regime = b.regime
            if b.regime == "RISK_OFF":
                rep.notes.append("regime gate: watchlist breadth RISK_OFF, no new entries this tick")
                return rep

        # 3. entries
        held = {p.symbol for p in self.broker.get_positions()}
        for sym in self.s.watchlist:
            if sym in held:
                continue
            q = quotes.get(sym)
            if q is None:
                rep.notes.append(f"{sym}: no price this tick; entry not evaluated")
                continue
            self._quotes[sym] = q
            st = self.supervisor.run_once(sym, self.data_dir / f"{sym}.csv", q, now, approve=self._approve, as_of=as_of)
            if st.proposal is not None and st.proposal.decision == "TRADE":
                rep.signals += 1
            if st.step == Step.DONE and st.execution_status:
                i = st.decision.intent
                rep.entries.append(f"{st.execution_status} BUY {i.qty} {sym} @ ≤₹{i.limit_price} stop ₹{i.stop} target ₹{i.target}")
            elif st.decision is not None and not st.decision.approved:
                rep.blocked[sym] = st.decision.reasons
            elif st.step == Step.HALTED:
                rep.blocked[sym] = [st.halted_reason]
            else:
                rep.no_trade.append(sym)
        return rep


def format_tick(r: TickReport) -> str:
    lines = [f"AUTOPILOT TICK {r.now:%Y-%m-%d %H:%M} IST [PAPER — simulated only] regime: {r.regime}"]
    lines += [f"  EXIT  {e}" for e in r.exits]
    lines += [f"  ENTRY {e}" for e in r.entries]
    lines += [f"  BLOCK {s}: {'; '.join(why)[:160]}" for s, why in r.blocked.items()]
    if r.no_trade:
        lines.append(f"  NO_TRADE {', '.join(r.no_trade)}")
    lines += [f"  note: {n}" for n in r.notes]
    return "\n".join(lines)
