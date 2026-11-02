"""Declarative strategies: entry rules, levels and exits are data, so the
backtester, portfolio lab, autopilot, live desk and reports all run exactly
the same rules.

A signal strategy gives, per bar, a list of named boolean conditions (ALL
must hold to signal), plus stop / target / score series. Everything is
computed from causal indicators, so row t never sees rows after t.

`target` is used by the risk manager's reward checks. When
`exit.take_profit` is False it is a PLANNING target only: the position is
not sold there, it exits on its trailing / trend rules instead.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..indicators.core import add_indicators
from ..market_data.csv_source import last_bar_as_of
from ..models import TradeProposal

Condition = tuple[pd.Series, str, str]   # (boolean series, label when true, label when false)


@dataclass(frozen=True)
class ExitPolicy:
    take_profit: bool = True                 # sell at target
    trail_atr: Optional[float] = None        # chandelier: highest close since entry - k * ATR14 (only ratchets up)
    close_below: Optional[str] = None        # exit when close < this indicator column (e.g. "sma50", "ll20")
    close_above: Optional[str] = None        # mean reversion: exit when close > this column (e.g. "sma5")
    max_hold_days: int = 10

    def describe(self) -> str:
        parts = ["stop (gap below stop exits at the open)"]
        if self.take_profit:
            parts.append("target")
        if self.trail_atr:
            parts.append(f"trailing stop {self.trail_atr}×ATR below the highest close")
        if self.close_below:
            parts.append(f"close < {self.close_below}")
        if self.close_above:
            parts.append(f"close > {self.close_above}")
        parts.append(f"max hold {self.max_hold_days} days")
        return ", ".join(parts)


@dataclass(frozen=True)
class Strategy:
    name: str
    version: str
    summary: str
    origin: str                                   # where the idea comes from (credited)
    params: object
    exit: ExitPolicy
    min_bars: int
    conditions: Callable[[pd.DataFrame, object], list[Condition]]
    levels: Callable[[pd.DataFrame, object], tuple[pd.Series, pd.Series, pd.Series]]   # stop, target, score
    notes: Callable[[pd.Series], list[str]] = field(default=lambda r: [])
    required: tuple[str, ...] = ("atr14",)
    kind: str = "signal"                          # "signal" (per stock) or "rotation" (portfolio)

    # ------------------------------------------------------------ vectorised
    def signals(self, x: pd.DataFrame) -> pd.DataFrame:
        """signal/stop/target/score for every row (row t uses rows <= t)."""
        conds = self.conditions(x, self.params)
        ok = pd.Series(True, index=x.index)
        for series, _, _ in conds:
            ok &= series.fillna(False).astype(bool)
        ok &= ~x[list(self.required)].isna().any(axis=1)
        ok &= pd.Series(np.arange(len(x)) >= self.min_bars - 1, index=x.index)
        stop, target, score = self.levels(x, self.params)
        ok &= (stop < x["close"]) & (target > x["close"])
        return pd.DataFrame({"signal": ok, "stop": stop.round(2), "target": target.round(2), "score": score})

    # ------------------------------------------------------------ one decision
    def evaluate(self, df: pd.DataFrame, symbol: str, data_source: str,
                 indicators: Optional[pd.DataFrame] = None) -> TradeProposal:
        """Decide on the LAST row given (caller must not pass future rows)."""
        as_of = last_bar_as_of(df)
        base = dict(symbol=symbol, strategy=self.name, strategy_version=self.version, as_of=as_of,
                    data_source=data_source)
        if len(df) < self.min_bars:
            return TradeProposal(decision="NO_TRADE", reasons=[f"only {len(df)} bars; need {self.min_bars}"], **base)
        x = indicators if indicators is not None else add_indicators(df)
        last = x.iloc[[-1]]
        if last[list(self.required)].isna().any(axis=None):
            return TradeProposal(decision="NO_TRADE", reasons=["indicators not yet available"], **base)
        why, against = [], []
        for series, yes, no in self.conditions(last, self.params):
            v = series.iloc[-1]
            (why if bool(v) and not pd.isna(v) else against).append(yes if bool(v) and not pd.isna(v) else no)
        notes = self.notes(last.iloc[-1])
        if against:
            return TradeProposal(decision="NO_TRADE", reasons=against + notes, contra=why, **base)
        stop, target, _ = self.levels(last, self.params)
        entry, st, tg = round(float(last["close"].iloc[-1]), 2), round(float(stop.iloc[-1]), 2), round(float(target.iloc[-1]), 2)
        if not (st < entry < tg):
            return TradeProposal(decision="NO_TRADE", reasons=[f"levels not usable (stop {st}, entry {entry}, target {tg})"],
                                 contra=why, **base)
        if not self.exit.take_profit:
            why.append(f"target ₹{tg} is for planning; exits: {self.exit.describe()}")
        return TradeProposal(decision="TRADE", reasons=why, contra=notes, entry=entry, stop=st, target=tg,
                             max_hold_days=self.exit.max_hold_days, **base)

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "kind": self.kind, "summary": self.summary,
                "origin": self.origin, "params": asdict(self.params), "exits": self.exit.describe()}


# ---------------------------------------------------------------- exits
def effective_stop(policy: ExitPolicy, initial_stop: float, closes_since_entry: pd.Series, atr_now: float) -> float:
    """Initial stop raised by the chandelier trail; never lowered."""
    stop = float(initial_stop)
    if policy.trail_atr and len(closes_since_entry) and not np.isnan(atr_now):
        stop = max(stop, float(closes_since_entry.max()) - policy.trail_atr * float(atr_now))
    return round(stop, 2)


def close_rule_exit(policy: ExitPolicy, row: pd.Series) -> str:
    """Rules judged on the close (exit at the next open in backtests, at the
    current price in a live/paper tick). Returns the reason or ""."""
    c = float(row["close"])
    if policy.close_below:
        v = row.get(policy.close_below, np.nan)
        if not pd.isna(v) and c < float(v):
            return f"close < {policy.close_below}"
    if policy.close_above:
        v = row.get(policy.close_above, np.nan)
        if not pd.isna(v) and c > float(v):
            return f"close > {policy.close_above}"
    return ""
