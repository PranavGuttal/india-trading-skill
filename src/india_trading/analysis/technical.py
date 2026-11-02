"""One-stock technical report from daily bars (no fundamentals).

Adapted from tradermonty's technical-analyst / us-stock-analysis and
day-trader-skill's trader-analyst idea, for NSE daily data: trend stage and
averages, 52-week position, swing support/resistance levels, momentum
(RSI, MACD), volatility (ATR), volume, relative strength vs Nifty 50 and the
stock's sector index, recent corporate actions, and what every registered
strategy says today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from ..indicators.core import add_indicators
from ..strategies import SIGNAL_STRATEGIES
from .screener import stage


@dataclass
class TechReport:
    symbol: str
    as_of: str
    source: str
    close: float
    change_pct: float
    stage: str
    sma: dict[str, float]
    high52: float
    low52: float
    pos52: float
    supports: list[float]
    resistances: list[float]
    rsi14: float
    macd_hist: float
    atr14: float
    atr_pct: float
    relvol: float
    rs_nifty: dict[str, float]
    rs_sector: dict[str, float]
    sector: str
    events: list[dict]
    strategies: dict[str, str] = field(default_factory=dict)


def swing_levels(x: pd.DataFrame, lookback: int = 120, w: int = 5, tol: float = 0.015) -> tuple[list[float], list[float]]:
    """Swing highs/lows (a bar that is the extreme of +/- w bars) in the last
    `lookback` bars, clustered within `tol`; split around the last close."""
    d = x.iloc[-lookback:].reset_index(drop=True)
    hi, lo = d["high"].to_numpy(float), d["low"].to_numpy(float)
    pts = []
    for i in range(w, len(d) - w):
        if hi[i] == hi[i - w:i + w + 1].max():
            pts.append(hi[i])
        if lo[i] == lo[i - w:i + w + 1].min():
            pts.append(lo[i])
    pts.sort()
    clusters: list[list[float]] = []
    for p in pts:
        if clusters and p <= clusters[-1][-1] * (1 + tol):
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [round(float(np.mean(c)), 2) for c in clusters]
    c = float(x["close"].iloc[-1])
    sup = sorted([l for l in levels if l < c], reverse=True)[:3]
    res = sorted([l for l in levels if l > c])[:3]
    return sup, res


def _rel(a: pd.Series, b: pd.Series, n: int) -> float:
    if len(a) <= n or len(b) <= n:
        return float("nan")
    return round(100 * ((a.iloc[-1] / a.iloc[-1 - n]) - (b.iloc[-1] / b.iloc[-1 - n])), 1)


def analyse(df: pd.DataFrame, symbol: str, source: str, nifty: Optional[pd.DataFrame] = None,
            sector_df: Optional[pd.DataFrame] = None, sector: str = "", events: Optional[list[dict]] = None,
            as_of: Optional[date] = None) -> TechReport:
    d = df.reset_index(drop=True)
    if as_of is not None:
        d = d[d["date"].dt.date <= as_of].reset_index(drop=True)
    if len(d) < 60:
        raise ValueError(f"{symbol}: need >= 60 bars, have {len(d)}")
    x = add_indicators(d)
    r = x.iloc[-1]
    last = r["date"]
    slope = float(x["sma150"].iloc[-1] - x["sma150"].iloc[-22]) if len(x) > 172 else float("nan")
    win = x.iloc[-252:]
    h52, l52 = float(win["high"].max()), float(win["low"].min())
    sup, res = swing_levels(x)

    def aligned(o: Optional[pd.DataFrame]) -> Optional[pd.Series]:
        if o is None:
            return None
        s = o.set_index(pd.DatetimeIndex(o["date"]))["close"]
        return s[s.index <= last]
    c = x.set_index(pd.DatetimeIndex(x["date"]))["close"]
    n, sec = aligned(nifty), aligned(sector_df)
    rs_n = {k: _rel(c, n, v) for k, v in (("1m", 21), ("3m", 63), ("6m", 126))} if n is not None else {}
    rs_s = {k: _rel(c, sec, v) for k, v in (("1m", 21), ("3m", 63), ("6m", 126))} if sec is not None else {}
    verdicts = {}
    for name, strat in SIGNAL_STRATEGIES.items():
        p = strat.evaluate(d, symbol, source, indicators=x)
        verdicts[name] = (f"TRADE entry ₹{p.entry} stop ₹{p.stop} target ₹{p.target}" if p.decision == "TRADE"
                          else "NO_TRADE: " + "; ".join(p.reasons[:2]))
    recent = [e for e in (events or []) if e["date"] >= str((last - pd.Timedelta(days=400)).date())]
    return TechReport(
        symbol=symbol, as_of=str(last.date()), source=source, close=round(float(r["close"]), 2),
        change_pct=round(100 * (float(r["close"]) / float(x["close"].iloc[-2]) - 1), 2), stage=stage(r, slope),
        sma={k: round(float(r[k]), 2) for k in ("sma20", "sma50", "sma150", "sma200") if not pd.isna(r[k])},
        high52=round(h52, 2), low52=round(l52, 2), pos52=round(100 * (float(r["close"]) - l52) / max(h52 - l52, 1e-9), 0),
        supports=sup, resistances=res, rsi14=round(float(r["rsi14"]), 1), macd_hist=round(float(r["macd_hist"]), 2),
        atr14=round(float(r["atr14"]), 2), atr_pct=round(100 * float(r["atr14"]) / float(r["close"]), 2),
        relvol=round(float(r["relvol20"]), 2) if not pd.isna(r["relvol20"]) else float("nan"),
        rs_nifty=rs_n, rs_sector=rs_s, sector=sector, events=recent[-6:], strategies=verdicts)


def format_tech(t: TechReport) -> str:
    sm = " | ".join(f"{k.upper()} {v:,.2f}{'↑' if t.close > v else '↓'}" for k, v in t.sma.items())
    lines = [f"{t.symbol} — technical report as of {t.as_of} | data {t.source}",
             f"  Close ₹{t.close:,.2f} ({t.change_pct:+.2f}% day) | stage {t.stage}",
             f"  {sm}   (↑ = price above)",
             f"  52-week range ₹{t.low52:,.2f} – ₹{t.high52:,.2f}; price at {t.pos52:.0f}% of the range",
             f"  Support {', '.join(f'₹{v:,.2f}' for v in t.supports) or '-'} | "
             f"resistance {', '.join(f'₹{v:,.2f}' for v in t.resistances) or '- (at highs)'}",
             f"  RSI14 {t.rsi14} | MACD hist {t.macd_hist:+.2f} | ATR14 ₹{t.atr14} ({t.atr_pct}%/day) | "
             f"volume {t.relvol}× 20-day average"]
    if t.rs_nifty:
        lines.append("  vs Nifty 50 (pp): " + ", ".join(f"{k} {v:+.1f}" for k, v in t.rs_nifty.items()))
    if t.rs_sector:
        lines.append(f"  vs sector {t.sector} (pp): " + ", ".join(f"{k} {v:+.1f}" for k, v in t.rs_sector.items()))
    if t.events:
        lines.append("  Corporate actions (last ~13 months): " + "; ".join(
            f"{e['date']} {e['type']} {e.get('amount', e.get('ratio', ''))}" for e in t.events))
    lines.append("  Strategies today:")
    lines += [f"    {k:20} {v[:150]}" for k, v in t.strategies.items()]
    lines.append("  Technical picture only — no earnings or valuation. Not advice.")
    return "\n".join(lines)
