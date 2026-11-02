"""Autopilot: one unattended PAPER trading tick over the watchlist.

Per tick, in this order:
  0. CAPITAL FLOOR: if equity (cash + positions at current prices) is below
     the floor, sell everything and engage the kill switch.
  1. EXITS for open paper positions, using the strategy's exit policy: gap
     through stop, stop (raised by a trailing stop where the strategy has
     one), target, close rules (e.g. close < SMA50), or max hold days. Exits
     are never blocked by entry limits or the kill switch (they only reduce risk).
  2. Market gate (default): no new entries while Nifty 50 is below its
     200-day average or its data is missing/stale ("watchlist" = breadth gate).
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
from ..analysis.market_gate import market_ok
from ..brokers.base import BrokerAdapter
from ..config import Settings
from ..execution.executor import ExecutionRefused
from ..indicators.core import add_indicators
from ..journal.store import Journal
from ..market_data.calendar import IST, NSECalendar
from ..market_data.csv_source import DataError, load_csv
from ..models import OrderIntent, Quote, Side
from ..risk.manager import KillSwitch
from ..strategies import get as get_strategy
from ..strategies.base import ExitPolicy, Strategy, close_rule_exit, effective_stop
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
    strategy: str = ""


def policy_exit(bar: tuple[float, float, float, float], stop: float, target: float, held_days: int,
                policy: ExitPolicy, close_rule: str = "") -> tuple[Optional[float], str]:
    """(exit price, reason) for one bar, or (None, "") to keep holding.
    Stop is checked before target when one bar touches both (conservative)."""
    o, h, l, c = bar
    if o <= stop:
        return o, "gap below stop"
    if l <= stop:
        return stop, "stop"
    if policy.take_profit and h >= target:
        return max(o, target), "target"
    if close_rule:
        return c, "trend exit (close < SMA50)" if close_rule == "close < sma50" else close_rule
    if held_days >= policy.max_hold_days:
        return c, "max hold"
    return None, ""


def exit_decision(bar: tuple[float, float, float, float], stop: float, target: float, sma50: float,
                  held_days: int, max_hold_days: int) -> tuple[Optional[float], str]:
    """ma_trend_pullback exits (target, close < SMA50, max hold)."""
    rule = "close < sma50" if not np.isnan(sma50) and bar[3] < sma50 else ""
    return policy_exit(bar, stop, target, held_days,
                       ExitPolicy(take_profit=True, close_below="sma50", max_hold_days=max_hold_days), rule)


class AutoPilot:
    def __init__(self, settings: Settings, broker: BrokerAdapter, journal: Journal, calendar: NSECalendar,
                 data_dir: str | Path, max_hold_days: Optional[int] = None, strategy: Optional[Strategy] = None):
        if broker.is_live:
            raise ExecutionRefused("autopilot is paper-only; it refuses live broker adapters")
        self.s, self.broker, self.journal, self.calendar = settings, broker, journal, calendar
        self.data_dir = Path(data_dir)
        self.strategy = strategy or get_strategy(settings.strategy)
        pol = self.strategy.exit
        self.policy = pol if max_hold_days is None else ExitPolicy(**{**pol.__dict__, "max_hold_days": max_hold_days})
        self.max_hold_days = self.policy.max_hold_days
        self.supervisor = Supervisor(settings, broker, journal, calendar, strategy=self.strategy.evaluate)
        self.kill = KillSwitch(settings.state_path("KILL_SWITCH"))
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

    def _sell(self, pos, q: Quote, px: float, why: str, today: date, now: datetime) -> str:
        self._quotes[pos.symbol] = q.model_copy(update={"price": round(px, 2)})
        intent = OrderIntent(symbol=pos.symbol, side=Side.SELL, qty=pos.qty, limit_price=round(px * 0.995, 2),
                             product=self.s.product, trade_date=str(today),
                             proposal_ref=f"autopilot-exit:{why}:{now.isoformat()}")
        o = self.broker.place_order(intent)
        msg = f"{o.status.value} SELL {o.filled_qty} {pos.symbol} @ {o.avg_fill_price} ({why}; {q.source})"
        self.journal.record("EXIT", "paper", msg, symbol=pos.symbol, intent_id=o.intent_id,
                            payload=o.model_dump(mode="json"))
        return msg

    def _floor_breached(self, positions, quotes: dict[str, Quote]) -> Optional[str]:
        if self.s.capital_floor_pct <= 0:
            return None
        equity = self.broker.cash() + sum(p.qty * (quotes[p.symbol].price if p.symbol in quotes else p.avg_price)
                                          for p in positions)
        if equity >= self.s.capital_floor:
            return None
        return (f"capital floor breached: equity ₹{equity:.2f} < ₹{self.s.capital_floor:.2f} "
                f"({self.s.capital_floor_pct:g}% of ₹{self.s.max_experimental_allocation_inr:.0f})")

    def tick(self, now: datetime, quotes: dict[str, Quote], as_of: Optional[date] = None,
             frames: Optional[dict[str, pd.DataFrame]] = None) -> TickReport:
        """quotes: current price per symbol (live read or replay close). With
        as_of set (replay), exits use that day's full OHLC bar."""
        rep = TickReport(now=now, strategy=self.strategy.name)
        today = now.astimezone(IST).date()
        frames = frames if frames is not None else self.load_frames(as_of)
        self._quotes = dict(quotes)
        positions = self.broker.get_positions()

        # 0. capital floor
        breach = self._floor_breached(positions, quotes)
        if breach:
            if not self.kill.engaged:
                self.kill.engage(breach)
                self.journal.record("KILL_SWITCH", "paper", "engaged: " + breach)
            rep.notes.append(breach + "; selling everything, kill switch engaged")
            for pos in positions:
                q = quotes.get(pos.symbol)
                if q is None:
                    rep.notes.append(f"{pos.symbol}: no price; cannot sell it this tick")
                    continue
                rep.exits.append(self._sell(pos, q, q.price, "capital floor", today, now))
            return rep

        # 1. exits
        for pos in positions:
            df, q = frames.get(pos.symbol), quotes.get(pos.symbol)
            if df is None or df.empty or q is None:
                rep.notes.append(f"{pos.symbol}: no price this tick; position left open")
                continue
            last = df.iloc[-1]
            is_today = as_of is not None and pd.Timestamp(last["date"]).date() == today
            if is_today:
                bar = (float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"]))
            else:
                bar = (q.price,) * 4
            pre = self.supervisor.preloaded.get(pos.symbol)
            if pre is not None and len(pre[3]) >= len(df):     # replay: causal indicators already computed
                x = pre[3].iloc[max(0, len(df) - 300):len(df)].reset_index(drop=True)
            else:
                x = add_indicators(df.iloc[-300:].reset_index(drop=True))
            prev = x.iloc[:-1] if is_today else x            # today's stop uses bars before today
            stop = pos.stop or 0.0
            if self.policy.trail_atr and len(prev):
                since = prev[prev["date"].dt.date >= pos.opened_at.astimezone(IST).date()]["close"]
                new = effective_stop(self.policy, stop, since, float(prev["atr14"].iloc[-1]))
                if new > stop and hasattr(self.broker, "update_stop") and self.broker.update_stop(pos.symbol, new):
                    rep.notes.append(f"{pos.symbol}: trailing stop raised ₹{stop:.2f} → ₹{new:.2f}")
                    stop = new
            row = x.iloc[-1].copy()
            row["close"] = bar[3]
            held = int(np.busday_count(pos.opened_at.astimezone(IST).date(), today))
            px, why = policy_exit(bar, stop, pos.target or float("inf"), held, self.policy,
                                  close_rule_exit(self.policy, row))
            if px is not None:
                rep.exits.append(self._sell(pos, q, px, why, today, now))

        # 2. market gate (entries only; exits above already ran)
        if self.s.regime_gate == "index":
            ok, note = market_ok(self.s.indices_dir, as_of or today, self.s.max_bar_age_days)
            rep.regime = "OPEN" if ok else ("CLOSED" if ok is False else "UNKNOWN")
            if ok is not True:
                rep.notes.append(note + "; no new entries this tick")
                return rep
        elif self.s.regime_gate == "watchlist":
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
    lines = [f"AUTOPILOT TICK {r.now:%Y-%m-%d %H:%M} IST [PAPER — simulated only] strategy {r.strategy} | regime: {r.regime}"]
    lines += [f"  EXIT  {e}" for e in r.exits]
    lines += [f"  ENTRY {e}" for e in r.entries]
    lines += [f"  BLOCK {s}: {'; '.join(why)[:160]}" for s, why in r.blocked.items()]
    if r.no_trade:
        lines.append(f"  NO_TRADE {', '.join(r.no_trade)}")
    lines += [f"  note: {n}" for n in r.notes]
    return "\n".join(lines)
