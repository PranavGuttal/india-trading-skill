"""NSE market regime from real index data (Nifty 50, India VIX) plus the
breadth of a stock universe.

Adapted for India from tradermonty's ftd-detector, ibd-distribution-day-
monitor, market-top-detector, uptrend-analyzer and exposure-coach:

- TREND FILTER (tested, docs/STRATEGY_LAB.md): Nifty 50 close vs its 200-day
  average. This is the only part with a backtest behind it.
- Distribution days: Nifty down >= 0.2% on higher volume than the day
  before, counted over the last 25 sessions; one expires once the index
  closes 5% above it. Days with zero/missing index volume are not counted.
- Follow-through day: after a >= 8% fall from the 63-day high, day 4+ of a
  rally attempt (no undercut of the low) closing up >= 1.25% on higher volume.
- India VIX level and its 1-year percentile.
- Breadth: share of the universe above its 50/200-day average, 52-week
  highs vs lows.

The exposure posture combines these with fixed, documented weights. It is a
HEURISTIC summary for humans, not a tested signal; say so when reporting it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from ..indicators.core import sma


@dataclass
class RegimeReport:
    as_of: str
    index_close: float
    sma50: float
    sma200: float
    trend_filter_on: bool
    sma200_rising: bool
    pct_from_high: float
    distribution_days: int
    distribution_dates: list[str]
    follow_through: Optional[str]
    rally_day: Optional[int]
    vix: Optional[float]
    vix_pctile: Optional[float]
    breadth50: Optional[float]
    breadth200: Optional[float]
    new_highs: Optional[int]
    new_lows: Optional[int]
    universe: int
    exposure_pct: int
    posture: str
    reasons: list[str] = field(default_factory=list)


def _slice(df: pd.DataFrame, as_of: Optional[date]) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    if as_of is not None:
        df = df[df["date"].dt.date <= as_of].reset_index(drop=True)
    return df


def distribution_days(ix: pd.DataFrame, window: int = 25, drop: float = -0.002, expiry: float = 0.05) -> list[int]:
    c, v = ix["close"].to_numpy(float), ix["volume"].to_numpy(float)
    n = len(ix)
    out = []
    for i in range(max(1, n - window), n):
        if v[i] <= 0 or v[i - 1] <= 0 or np.isnan(v[i]) or np.isnan(v[i - 1]):
            continue
        if c[i] / c[i - 1] - 1 <= drop and v[i] > v[i - 1]:
            if c[i:].max() < c[i] * (1 + expiry):
                out.append(i)
    return out


def follow_through(ix: pd.DataFrame, lookback: int = 63, correction: float = 0.08, gain: float = 0.0125,
                   min_day: int = 4) -> tuple[Optional[int], Optional[int]]:
    """(index of the latest follow-through day within the last `lookback`
    bars, current rally-attempt day number or None)."""
    c, lo, v = ix["close"].to_numpy(float), ix["low"].to_numpy(float), ix["volume"].to_numpy(float)
    n = len(ix)
    if n < lookback + 5:
        return None, None
    start = n - lookback
    hi = c[max(0, start - lookback):start + 1].max()
    low_i, ftd, day = None, None, None
    for i in range(start, n):
        hi = max(hi, c[i])
        if c[i] <= hi * (1 - correction) and (low_i is None or lo[i] < lo[low_i]):
            low_i, day = i, None                       # new low in a correction: attempt resets
            continue
        if low_i is None:
            continue
        if lo[i] < lo[low_i]:
            low_i, day = i, None
            continue
        if day is None:
            if c[i] > c[i - 1]:
                day = 1
            continue
        day += 1
        if day >= min_day and c[i] / c[i - 1] - 1 >= gain and v[i] > v[i - 1] > 0:
            ftd = i
    return ftd, day


def breadth(frames: dict[str, pd.DataFrame], as_of: Optional[date]) -> tuple[Optional[float], Optional[float], int, int, int]:
    a50 = a200 = hi = lo = n = 0
    for df in frames.values():
        d = _slice(df, as_of)
        if len(d) < 200:
            continue
        c = d["close"]
        n += 1
        a50 += c.iloc[-1] > c.iloc[-50:].mean()
        a200 += c.iloc[-1] > c.iloc[-200:].mean()
        hi += d["high"].iloc[-1] >= d["high"].iloc[-252:].max()
        lo += d["low"].iloc[-1] <= d["low"].iloc[-252:].min()
    if not n:
        return None, None, 0, 0, 0
    return round(100 * a50 / n, 1), round(100 * a200 / n, 1), hi, lo, n


def compute(index_df: pd.DataFrame, vix_df: Optional[pd.DataFrame] = None,
            frames: Optional[dict[str, pd.DataFrame]] = None, as_of: Optional[date] = None) -> RegimeReport:
    ix = _slice(index_df, as_of)
    if len(ix) < 221:
        raise ValueError(f"need >= 221 index bars for the 200-day average, have {len(ix)}")
    c = ix["close"]
    s50, s200 = sma(c, 50), sma(c, 200)
    close, m50, m200 = float(c.iloc[-1]), float(s50.iloc[-1]), float(s200.iloc[-1])
    rising = bool(s200.iloc[-1] > s200.iloc[-21])
    high63 = float(c.iloc[-63:].max())
    dd = distribution_days(ix)
    ftd_i, rally_day = follow_through(ix)
    vix = pct = None
    if vix_df is not None:
        v = _slice(vix_df, as_of)
        if len(v):
            vix = round(float(v["close"].iloc[-1]), 2)
            last = v["close"].iloc[-252:]
            pct = round(100 * float((last < vix).mean()), 0)
    b50, b200, nh, nl, n = breadth(frames or {}, as_of)

    score, why = 100, []
    if close < m200:
        score -= 40; why.append(f"Nifty below its 200-day average ({close:,.0f} < {m200:,.0f}) — trend filter OFF")
    else:
        why.append(f"Nifty above its 200-day average ({close:,.0f} > {m200:,.0f}) — trend filter ON")
    if close < m50:
        score -= 20; why.append("below the 50-day average")
    if not rising:
        score -= 10; why.append("200-day average falling")
    if len(dd) >= 7:
        score -= 30; why.append(f"{len(dd)} distribution days in 25 sessions (heavy selling)")
    elif len(dd) >= 5:
        score -= 20; why.append(f"{len(dd)} distribution days in 25 sessions")
    if pct is not None and pct >= 80:
        score -= 15; why.append(f"India VIX {vix} is in the top 20% of the past year (fear)")
    if b50 is not None and b50 < 40:
        score -= 15; why.append(f"only {b50:.0f}% of the universe above its 50-day average")
    recent_ftd = ftd_i is not None and ftd_i >= len(ix) - 25
    if recent_ftd and close < m50:
        score += 20; why.append(f"follow-through day on {ix['date'].iloc[ftd_i].date()} (possible new uptrend)")
    score = int(max(0, min(100, round(score / 10) * 10)))
    posture = ("RISK_ON — full exposure allowed" if score >= 80 else
               "CAUTION — smaller size, only the best setups" if score >= 50 else
               "DEFENSIVE — few or no new entries" if score >= 20 else
               "RISK_OFF — protect capital, no new entries")
    return RegimeReport(
        as_of=str(ix["date"].iloc[-1].date()), index_close=round(close, 2), sma50=round(m50, 2), sma200=round(m200, 2),
        trend_filter_on=close > m200, sma200_rising=rising, pct_from_high=round(100 * (close / high63 - 1), 1),
        distribution_days=len(dd), distribution_dates=[str(ix["date"].iloc[i].date()) for i in dd],
        follow_through=str(ix["date"].iloc[ftd_i].date()) if ftd_i is not None else None, rally_day=rally_day,
        vix=vix, vix_pctile=pct, breadth50=b50, breadth200=b200, new_highs=nh if n else None,
        new_lows=nl if n else None, universe=n, exposure_pct=score, posture=posture, reasons=why)


def format_regime(r: RegimeReport) -> str:
    lines = [f"NSE MARKET REGIME as of {r.as_of} (Nifty 50 + India VIX from Yahoo Finance, unofficial)",
             f"  Nifty 50 {r.index_close:,.2f} | SMA50 {r.sma50:,.2f} | SMA200 {r.sma200:,.2f} "
             f"({'rising' if r.sma200_rising else 'falling'}) | {r.pct_from_high:+.1f}% vs 63-day high",
             f"  TREND FILTER (tested rule): {'ON — Nifty above SMA200' if r.trend_filter_on else 'OFF — Nifty below SMA200'}",
             f"  Distribution days (25 sessions): {r.distribution_days}"
             + (f" ({', '.join(r.distribution_dates[-5:])})" if r.distribution_dates else ""),
             f"  Follow-through day (63 sessions): {r.follow_through or 'none'}"
             + (f" | rally attempt day {r.rally_day}" if r.rally_day else "")]
    if r.vix is not None:
        lines.append(f"  India VIX {r.vix} (higher than {r.vix_pctile:.0f}% of the past year's closes)")
    if r.universe:
        lines.append(f"  Breadth of {r.universe} stocks: {r.breadth50}% > SMA50, {r.breadth200}% > SMA200, "
                     f"52-week highs {r.new_highs} / lows {r.new_lows}")
    lines.append(f"  EXPOSURE POSTURE {r.exposure_pct}%: {r.posture}  (heuristic summary, not a tested signal)")
    lines += [f"   - {w}" for w in r.reasons]
    return "\n".join(lines)
