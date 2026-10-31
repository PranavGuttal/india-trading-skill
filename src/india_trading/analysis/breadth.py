"""Breadth and regime of YOUR watchlist, from local daily CSVs only.

Idea from claude-trading-skills' breadth/uptrend analysers (MIT; no code
copied). This is NOT Nifty or NSE-wide breadth: no verified source for that
is wired in. With a handful of symbols the reading is noisy; it says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from ..indicators.core import sma

RISK_ON_PCT = 60.0
RISK_OFF_PCT = 40.0
MIN_SYMBOLS = 5


@dataclass
class Breadth:
    as_of: str
    symbols: int
    pct_above_sma50: float
    pct_above_sma200: Optional[float]
    pct_sma20_over_sma50: float
    advancers: int
    decliners: int
    new_highs_52w: int
    new_lows_52w: int
    regime: str
    notes: list[str] = field(default_factory=list)


def compute(frames: dict[str, pd.DataFrame], as_of: Optional[date] = None) -> Breadth:
    rows = []
    for sym, df in frames.items():
        x = df if as_of is None else df[df["date"].dt.date <= as_of]
        if len(x) < 50:
            continue
        c = x["close"].reset_index(drop=True)
        s200 = sma(c, 200).iloc[-1] if len(c) >= 200 else float("nan")
        hi52, lo52 = c.tail(250).max(), c.tail(250).min()
        rows.append({
            "date": pd.Timestamp(x["date"].iloc[-1]).date(),
            "above50": c.iloc[-1] > sma(c, 50).iloc[-1],
            "above200": None if pd.isna(s200) else bool(c.iloc[-1] > s200),
            "trend": sma(c, 20).iloc[-1] > sma(c, 50).iloc[-1],
            "chg": c.iloc[-1] - c.iloc[-2],
            "high": len(c) >= 250 and c.iloc[-1] >= hi52,
            "low": len(c) >= 250 and c.iloc[-1] <= lo52,
        })
    notes = []
    if not rows:
        return Breadth(str(as_of or ""), 0, 0.0, None, 0.0, 0, 0, 0, 0, "UNKNOWN",
                       ["no symbol has 50+ bars; breadth unavailable"])
    n = len(rows)
    pct = lambda k: round(100 * sum(bool(r[k]) for r in rows) / n, 1)
    with200 = [r for r in rows if r["above200"] is not None]
    p200 = round(100 * sum(r["above200"] for r in with200) / len(with200), 1) if with200 else None
    p50 = pct("above50")
    regime = "RISK_ON" if p50 >= RISK_ON_PCT else "RISK_OFF" if p50 <= RISK_OFF_PCT else "NEUTRAL"
    dates = {r["date"] for r in rows}
    if len(dates) > 1:
        notes.append(f"symbols end on different dates ({min(dates)} … {max(dates)}); some data is stale")
    if n < MIN_SYMBOLS:
        notes.append(f"only {n} symbols: breadth this narrow is noisy, treat the regime as a hint")
    notes.append("watchlist breadth only, not NSE-wide breadth")
    return Breadth(
        as_of=str(max(dates)), symbols=n, pct_above_sma50=p50, pct_above_sma200=p200,
        pct_sma20_over_sma50=pct("trend"),
        advancers=sum(r["chg"] > 0 for r in rows), decliners=sum(r["chg"] < 0 for r in rows),
        new_highs_52w=sum(bool(r["high"]) for r in rows), new_lows_52w=sum(bool(r["low"]) for r in rows),
        regime=regime, notes=notes,
    )


def format_breadth(b: Breadth) -> str:
    return "\n".join([
        f"BREADTH as of {b.as_of} | {b.symbols} symbols | regime {b.regime} "
        f"(RISK_ON if ≥{RISK_ON_PCT:.0f}% above SMA50, RISK_OFF if ≤{RISK_OFF_PCT:.0f}%)",
        f"  above SMA50 {b.pct_above_sma50}% | above SMA200 {b.pct_above_sma200 if b.pct_above_sma200 is not None else 'n/a'}%"
        f" | SMA20>SMA50 {b.pct_sma20_over_sma50}%",
        f"  advancers {b.advancers} / decliners {b.decliners} | 52-week highs {b.new_highs_52w} / lows {b.new_lows_52w}",
    ] + [f"  note: {n}" for n in b.notes])
