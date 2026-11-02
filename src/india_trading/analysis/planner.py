"""Trade planning: position size, R-multiple targets, charges, exits.

Adapted from tradermonty position-sizer / breakout-trade-planner and
day-trader-skill trader-budget / trader-exit, for NSE delivery trades with
Groww charges and whole shares only.

size()       whole-share quantity for a ₹ risk and a ₹ budget, with the loss
             at the stop INCLUDING round-trip charges (what you really lose).
plan()       a complete plan: entry/stop/targets at 1R-3R, size, charges,
             break-even, trailing rule, and the risk manager's verdict.
exit_plan()  for an open position: effective (trailing) stop, close-rule
             status, distance to stop/target in R, days held vs max hold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ..config import Settings
from ..risk.costs import estimate_charges, roundtrip_costs
from ..strategies.base import ExitPolicy, close_rule_exit, effective_stop


@dataclass
class SizeResult:
    qty: int
    value: float
    buy_costs: float
    roundtrip_costs: float
    loss_at_stop: float
    limited_by: str
    notes: list[str] = field(default_factory=list)


def size(entry: float, stop: float, risk_inr: float, budget_inr: float, s: Settings,
         target: Optional[float] = None) -> SizeResult:
    """Largest whole-share qty whose loss at the stop incl. charges <= risk_inr
    and whose value + buy charges <= budget_inr."""
    if not (stop < entry):
        raise ValueError("stop must be below entry for a long trade")
    exit_px = target if target else entry
    qty = max(0, min(math.floor(risk_inr / (entry - stop)), math.floor(budget_inr / entry)))
    limited = "risk" if math.floor(risk_inr / (entry - stop)) <= math.floor(budget_inr / entry) else "budget"
    while qty > 0:
        v = qty * entry
        bc = estimate_charges(v, "BUY", s.product, s.charges).total
        rt = roundtrip_costs(v, qty * stop, s.product, s.charges)
        if qty * (entry - stop) + rt <= risk_inr and v + bc <= budget_inr:
            rt_t = roundtrip_costs(v, qty * exit_px, s.product, s.charges)
            return SizeResult(qty, round(v, 2), round(bc, 2), round(rt_t, 2), round(qty * (entry - stop) + rt, 2), limited)
        qty -= 1
        limited = "charges"
    return SizeResult(0, 0.0, 0.0, 0.0, 0.0, "charges" if risk_inr >= entry - stop else "risk",
                      ["no whole share fits once charges are included — the budget/risk is too small for this stock"])


@dataclass
class Plan:
    symbol: str
    strategy: str
    entry: float
    stop: float
    target: float
    take_profit: bool
    size: SizeResult
    r_inr: float
    targets: dict[str, float]
    breakeven: float
    exit_rules: str
    notes: list[str] = field(default_factory=list)


def plan(symbol: str, entry: float, stop: float, target: float, s: Settings, policy: ExitPolicy,
         strategy: str = "manual", risk_inr: Optional[float] = None, budget_inr: Optional[float] = None) -> Plan:
    risk = risk_inr if risk_inr is not None else s.max_risk_per_trade_inr
    budget = budget_inr if budget_inr is not None else min(s.max_single_order_value_inr, s.max_experimental_allocation_inr)
    sz = size(entry, stop, risk, budget, s, target)
    r = entry - stop
    notes = []
    be = entry
    if sz.qty:
        be = round(entry + sz.roundtrip_costs / sz.qty, 2)
        if sz.roundtrip_costs / sz.value > 0.01:
            notes.append(f"charges are {100 * sz.roundtrip_costs / sz.value:.1f}% of the position — a larger position "
                         "or fewer trades would keep more of the move")
    if (target - entry) / r < s.min_reward_risk:
        notes.append(f"reward:risk {(target - entry) / r:.2f} is below the {s.min_reward_risk} minimum")
    return Plan(symbol, strategy, round(entry, 2), round(stop, 2), round(target, 2), policy.take_profit, sz,
                round(r, 2), {f"{k}R": round(entry + k * r, 2) for k in (1, 2, 3)}, be, policy.describe(), notes)


def format_plan(p: Plan) -> str:
    z = p.size
    lines = [f"TRADE PLAN {p.symbol} ({p.strategy}) — research only, not advice",
             f"  Entry ₹{p.entry:,.2f} | stop ₹{p.stop:,.2f} (1R = ₹{p.r_inr:,.2f}/share, "
             f"{100 * p.r_inr / p.entry:.1f}%) | {'target' if p.take_profit else 'planning target'} ₹{p.target:,.2f}",
             "  R-multiples: " + ", ".join(f"{k} ₹{v:,.2f}" for k, v in p.targets.items()),
             f"  Size: {z.qty} shares = ₹{z.value:,.2f} (limited by {z.limited_by}); buy charges ₹{z.buy_costs:.2f}, "
             f"round trip ≈ ₹{z.roundtrip_costs:.2f}",
             f"  Loss if the stop is hit, incl. charges: ₹{z.loss_at_stop:.2f} | break-even after charges ₹{p.breakeven:,.2f}",
             f"  Exits: {p.exit_rules}"]
    lines += [f"  note: {n}" for n in z.notes + p.notes]
    return "\n".join(lines)


def exit_plan(pos_symbol: str, qty: int, avg: float, stop: float, target: Optional[float], opened: str,
              x: pd.DataFrame, policy: ExitPolicy) -> dict:
    """x: indicators up to today. Returns the effective stop and status."""
    since = x[x["date"].dt.date >= pd.Timestamp(opened).date()]["close"]
    atr = float(x["atr14"].iloc[-1])
    eff = effective_stop(policy, stop, since, atr)
    c = float(x["close"].iloc[-1])
    r = max(avg - stop, 1e-9)
    held = int(len(since))
    return {
        "symbol": pos_symbol, "qty": qty, "avg": round(avg, 2), "close": round(c, 2),
        "open_pnl": round(qty * (c - avg), 2), "r_now": round((c - avg) / r, 2),
        "stop": round(stop, 2), "effective_stop": eff, "raise_stop": eff > stop,
        "dist_to_stop_pct": round(100 * (c / eff - 1), 2),
        "target": target, "close_rule": close_rule_exit(policy, x.iloc[-1]) or "ok",
        "held_bars": held, "max_hold": policy.max_hold_days, "time_exit_due": held >= policy.max_hold_days,
    }
