"""Time machine: Monte-Carlo replay of ONE planned long trade on daily bars.

Idea from day-trader-skill's trader-timemachine (MIT; no code copied), adapted
to NSE delivery trades on daily bars:

* Pool: each past bar as ratios (open, high, low, close) / previous close,
  taken from the last `lookback` bars of the stock's OWN history.
* One path: start at the entry price; for each holding day draw a random past
  bar, scale it to the current price, then check gap-through-stop, stop,
  target (stop first when a bar touches both: conservative). If neither is hit
  by `max_hold_days`, exit at that day's close.
* Charges for the given quantity come from risk/costs.py.

It is a simulation built from recent bars, not a prediction: news, results,
circuit limits and regime changes can produce moves the pool never saw.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import Settings
from ..risk.costs import roundtrip_costs

MIN_POOL = 60


@dataclass
class TimeMachineResult:
    symbol: str
    entry: float
    stop: float
    target: float
    qty: int
    max_hold_days: int
    paths: int
    pool_size: int
    pool_from: str
    pool_to: str
    p_target: float
    p_stop: float
    p_gap_stop: float
    p_time: float
    p_green_net: float
    avg_r: float
    avg_net_inr: float
    exit_pcts: dict[str, float] = field(default_factory=dict)
    data_source: str = ""

    @property
    def r_target(self) -> float:
        return (self.target - self.entry) / (self.entry - self.stop)

    def verdict(self) -> str:
        """Lean = share of decided paths that hit the target minus the
        break-even hit rate for this reward:risk (1 / (1 + R))."""
        decided = self.p_target + self.p_stop
        if decided == 0:
            return "No path reached the target or the stop within the holding period."
        lean = self.p_target / decided - 1 / (1 + self.r_target)
        pts = abs(lean) * 100
        side = "target" if lean > 0 else "stop"
        if pts < 5:
            word = "Close to break-even"
        elif pts < 15:
            word = f"Leans toward the {side}"
        else:
            word = f"Strongly toward the {side}"
        note = " — but the average result after charges is negative" if lean > 0 and self.avg_net_inr <= 0 else ""
        return f"{word} ({lean * 100:+.1f} pts vs the {1 / (1 + self.r_target):.0%} break-even hit rate){note}."


def build_pool(df: pd.DataFrame, lookback: int = 250) -> np.ndarray:
    """(n, 4) array of open/high/low/close divided by the previous close."""
    x = df.tail(lookback + 1).reset_index(drop=True)
    prev = x["close"].shift(1)
    pool = (x[["open", "high", "low", "close"]].div(prev, axis=0)).iloc[1:].to_numpy(dtype=float)
    return pool[np.isfinite(pool).all(axis=1)]


def simulate(
    df: pd.DataFrame,
    symbol: str,
    entry: float,
    stop: float,
    target: float,
    settings: Settings,
    qty: int = 1,
    max_hold_days: int = 10,
    paths: int = 10_000,
    lookback: int = 250,
    seed: int = 19,
    data_source: str = "",
) -> TimeMachineResult:
    if not stop < entry < target:
        raise ValueError("a long plan needs stop < entry < target")
    if qty < 1 or max_hold_days < 1 or paths < 1:
        raise ValueError("qty, max_hold_days and paths must be >= 1")
    pool = build_pool(df, lookback)
    if len(pool) < MIN_POOL:
        raise ValueError(f"only {len(pool)} usable bars; the time machine needs at least {MIN_POOL}")

    rng = np.random.default_rng(seed)
    draws = pool[rng.integers(0, len(pool), size=(paths, max_hold_days))]   # (paths, days, 4)
    price = np.full(paths, float(entry))
    exit_px = np.full(paths, np.nan)
    outcome = np.zeros(paths, dtype=np.int8)        # 0 open, 1 target, 2 stop, 3 gap stop, 4 time
    for day in range(max_hold_days):
        live = outcome == 0
        o, h, l, c = (price * draws[:, day, k] for k in range(4))
        gap = live & (o <= stop)
        hit_stop = live & ~gap & (l <= stop)
        hit_target = live & ~gap & ~hit_stop & (h >= target)
        exit_px[gap], outcome[gap] = o[gap], 3
        exit_px[hit_stop], outcome[hit_stop] = stop, 2
        exit_px[hit_target], outcome[hit_target] = np.maximum(o, target)[hit_target], 1
        price = np.where(outcome == 0, c, price)
    timed = outcome == 0
    exit_px[timed], outcome[timed] = price[timed], 4

    slip = settings.slippage_bps / 10_000
    fill_out = exit_px * (1 - slip)
    charges = np.array([roundtrip_costs(qty * entry, qty * px, settings.product, settings.charges) for px in fill_out])
    net = qty * (fill_out - entry) - charges
    risk = entry - stop
    pct = {f"p{q}": round(float(np.percentile(exit_px, q)), 2) for q in (5, 25, 50, 75, 95)}
    tail = df.tail(lookback + 1)
    return TimeMachineResult(
        symbol=symbol, entry=entry, stop=stop, target=target, qty=qty, max_hold_days=max_hold_days,
        paths=paths, pool_size=len(pool),
        pool_from=str(pd.Timestamp(tail["date"].iloc[1]).date()), pool_to=str(pd.Timestamp(tail["date"].iloc[-1]).date()),
        p_target=round(float(np.mean(outcome == 1)), 4), p_stop=round(float(np.mean(outcome == 2)), 4),
        p_gap_stop=round(float(np.mean(outcome == 3)), 4), p_time=round(float(np.mean(outcome == 4)), 4),
        p_green_net=round(float(np.mean(net > 0)), 4),
        avg_r=round(float(np.mean((exit_px - entry) / risk)), 3), avg_net_inr=round(float(np.mean(net)), 2),
        exit_pcts=pct, data_source=data_source,
    )


def format_result(r: TimeMachineResult) -> str:
    return "\n".join([
        f"TIME MACHINE {r.symbol} | data {r.data_source} | pool {r.pool_size} daily bars {r.pool_from} → {r.pool_to}",
        f"Plan: BUY {r.qty} @ ₹{r.entry:.2f}  stop ₹{r.stop:.2f}  target ₹{r.target:.2f} ({r.r_target:.2f}R)  max hold {r.max_hold_days}d",
        f"{r.paths:,} simulated paths:",
        f"  target first {r.p_target:.1%} | stop {r.p_stop:.1%} | gap through stop {r.p_gap_stop:.1%} | time exit {r.p_time:.1%}",
        f"  average result {r.avg_r:+.2f}R before charges | average net ₹{r.avg_net_inr:+.2f} after Groww charges for {r.qty} share(s)",
        f"  profitable after charges: {r.p_green_net:.1%} of paths",
        f"  exit price percentiles: " + "  ".join(f"{k} ₹{v}" for k, v in r.exit_pcts.items()),
        "VERDICT: " + r.verdict(),
        "This is a simulation from the stock's own recent bars, not a prediction or advice.",
    ])
