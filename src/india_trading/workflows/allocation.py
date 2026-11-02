"""Allocation pilot (PAPER): portfolio strategies that rebalance monthly.

  etf_trend            hold an index ETF (default NIFTYBEES) while Nifty 50
                       closes above its 200-day average at month end; cash otherwise
  trend_filtered_core  same rule, holding the whole universe in equal weight
  momentum_rotation    top 5 risk-adjusted-momentum stocks, regime-filtered

These had the best risk profile in the strategy lab (docs/STRATEGY_LAB.md):
lower drawdowns than buy & hold, but LOWER returns. None beat buy & hold.

Checks before any paper order (deterministic, fail closed): kill switch,
capital floor (sells everything and engages the kill switch if breached),
whole shares, cash incl. charges, the per-order cap, a fresh price per
symbol. Orders are paper only: this class refuses a live broker. It uses
its own paper account (state/allocation/) so it never mixes with the
swing autopilot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from ..brokers.paper_broker import PaperBroker
from ..config import Settings
from ..execution.executor import ExecutionRefused
from ..indicators.core import add_indicators
from ..journal.store import Journal
from ..market_data.calendar import IST
from ..models import OrderIntent, Quote, Side
from ..risk.costs import estimate_charges
from ..risk.manager import KillSwitch
from ..strategies import rotation

ALLOCATION_STRATEGIES = {
    "etf_trend": "Index ETF while Nifty 50 > its 200-day average (month-end check); cash otherwise.",
    "trend_filtered_core": "Whole universe, equal weight, while Nifty 50 > its 200-day average; cash otherwise.",
    "momentum_rotation": "Top 5 risk-adjusted momentum stocks above their 200-day average; cash when Nifty 50 < SMA200.",
}


@dataclass
class AllocationView:
    strategy: str
    as_of: str
    regime_on: bool
    nifty: float
    nifty_sma200: float
    targets: list[str]
    ranks: list[tuple[str, float]] = field(default_factory=list)
    is_month_end: bool = False
    next_check: str = ""


def _month_end(dates: pd.Series) -> bool:
    """True when the last bar is the last trading day of its month (by weekday calendar)."""
    last = pd.Timestamp(dates.iloc[-1])
    nxt = pd.bdate_range(last + pd.Timedelta(days=1), periods=1)[0]
    return nxt.month != last.month


def targets(strategy: str, nifty: pd.DataFrame, frames: dict[str, pd.DataFrame], held: set[str],
            etf: str = "NIFTYBEES") -> AllocationView:
    if strategy not in ALLOCATION_STRATEGIES:
        raise KeyError(f"unknown allocation strategy {strategy!r}; choose {', '.join(ALLOCATION_STRATEGIES)}")
    c = nifty["close"].reset_index(drop=True)
    if len(c) < 200:
        raise ValueError("need >= 200 Nifty 50 bars (run data-fetch --indices)")
    sma200 = float(c.iloc[-200:].mean())
    on = float(c.iloc[-1]) > sma200
    last = pd.Timestamp(nifty["date"].iloc[-1])
    month_last = pd.bdate_range(last, last + pd.offsets.MonthEnd(0))[-1]
    view = AllocationView(strategy, str(last.date()), on, round(float(c.iloc[-1]), 2), round(sma200, 2), [],
                          is_month_end=_month_end(nifty["date"]), next_check=str(month_last.date()))
    if not on:
        return view
    if strategy == "etf_trend":
        view.targets = [etf]
    elif strategy == "trend_filtered_core":
        view.targets = sorted(frames)
    else:
        scores = {}
        for sym, df in frames.items():
            x = add_indicators(df.iloc[-300:].reset_index(drop=True))
            scores[sym] = float(rotation.momentum_score(x).iloc[-1])
        ranked = rotation.rank_universe(scores)
        view.ranks = [(s, round(v, 3)) for s, v in ranked]
        rank = {s: k + 1 for k, (s, _) in enumerate(ranked)}
        keep = [s for s in held if rank.get(s, 10**6) <= rotation.PARAMS.hold_rank]
        view.targets = sorted(keep + [s for s, _ in ranked if s not in keep][: max(0, rotation.PARAMS.top_n - len(keep))])
    return view


def format_view(v: AllocationView, held: dict[str, int]) -> str:
    lines = [f"ALLOCATION {v.strategy} as of {v.as_of}: {ALLOCATION_STRATEGIES[v.strategy]}",
             f"  Nifty 50 {v.nifty:,.2f} vs SMA200 {v.nifty_sma200:,.2f} → regime {'ON (invest)' if v.regime_on else 'OFF (cash)'}",
             f"  Target holdings: {', '.join(v.targets) or 'none — cash'}",
             f"  Paper holdings now: {', '.join(f'{s}×{q}' for s, q in held.items()) or 'none'}",
             f"  Rebalance day: {'TODAY (last trading day of the month)' if v.is_month_end else v.next_check + ' (month end)'}"]
    if v.ranks:
        lines.append("  Momentum ranks: " + ", ".join(f"{k + 1}.{s}" for k, (s, _) in enumerate(v.ranks[:10])))
    return "\n".join(lines)


class AllocationPilot:
    def __init__(self, settings: Settings, journal: Journal):
        self.s = settings
        state = settings.state_path("allocation")
        state.mkdir(parents=True, exist_ok=True)
        self._q: dict[str, Quote] = {}
        self.broker = PaperBroker(state / "paper.db", settings.max_experimental_allocation_inr, settings.charges,
                                  price_provider=lambda sym: self._q[sym], slippage_bps=settings.slippage_bps)
        if self.broker.is_live:
            raise ExecutionRefused("allocation pilot is paper-only")
        self.journal = journal
        self.kill = KillSwitch(settings.state_path("KILL_SWITCH"))

    def held(self) -> dict[str, int]:
        return {p.symbol: p.qty for p in self.broker.get_positions()}

    def rebalance(self, view: AllocationView, quotes: dict[str, Quote], now: datetime) -> list[str]:
        out: list[str] = []
        self._q = dict(quotes)
        today = str(now.astimezone(IST).date())
        positions = self.broker.get_positions()
        missing = [p.symbol for p in positions if p.symbol not in quotes] + [t for t in view.targets if t not in quotes]
        if missing:
            return [f"REFUSED: no current price for {', '.join(sorted(set(missing)))}"]
        equity = self.broker.cash() + sum(p.qty * quotes[p.symbol].price for p in positions)
        floor_hit = self.s.capital_floor_pct > 0 and equity < self.s.capital_floor
        if floor_hit:
            why = f"capital floor breached: equity ₹{equity:.2f} < ₹{self.s.capital_floor:.2f}"
            if not self.kill.engaged:
                self.kill.engage(why)
                self.journal.record("KILL_SWITCH", "paper", "engaged: " + why)
            out.append(why + "; selling everything, kill switch engaged")
        sells = [p for p in positions if floor_hit or p.symbol not in view.targets]
        for p in sells:
            out.append(self._order(p.symbol, Side.SELL, p.qty, quotes[p.symbol], today, view.strategy))
        if floor_hit or self.kill.engaged:
            if self.kill.engaged and not floor_hit:
                out.append("kill switch engaged: no buys (sells above still ran)")
            return out
        held = {p.symbol for p in positions if p.symbol in view.targets}
        buys = [t for t in view.targets if t not in held]
        if not buys:
            return out or ["nothing to do: holdings already match the targets"]
        equity = self.broker.cash() + sum(p.qty * quotes[p.symbol].price for p in self.broker.get_positions())
        per = equity / max(1, len(view.targets))
        for sym in buys:
            q = quotes[sym]
            budget = min(per, self.broker.cash(), self.s.max_single_order_value_inr)
            qty = int(budget // (q.price * (1 + self.s.slippage_bps / 10_000)))
            while qty > 0 and qty * q.price + estimate_charges(qty * q.price, "BUY", self.s.product, self.s.charges).total > budget:
                qty -= 1
            if qty <= 0:
                out.append(f"SKIP BUY {sym}: ₹{budget:,.2f} does not buy one share at ₹{q.price:,.2f} with charges")
                continue
            out.append(self._order(sym, Side.BUY, qty, q, today, view.strategy))
        return out

    def _order(self, sym: str, side: Side, qty: int, q: Quote, today: str, strategy: str) -> str:
        px = q.price * (1.005 if side == Side.BUY else 0.995)
        intent = OrderIntent(symbol=sym, side=side, qty=qty, limit_price=round(px, 2), product=self.s.product,
                             trade_date=today, proposal_ref=f"allocation:{strategy}:{today}")
        o = self.broker.place_order(intent)
        msg = f"{o.status.value} {side.value} {o.filled_qty} {sym} @ {o.avg_fill_price} ({q.source})"
        self.journal.record("ALLOCATION", "paper", msg, symbol=sym, strategy=strategy, intent_id=o.intent_id,
                            payload=o.model_dump(mode="json"))
        return msg
