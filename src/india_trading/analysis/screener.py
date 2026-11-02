"""Multi-setup stock screener over a universe of daily CSVs.

Adapted for NSE from tradermonty (vcp-screener, canslim-screener technical
part, stockbee momentum-burst / episodic-pivot, uptrend-analyzer) and
day-trader-skill's trader-scanner. Technical data only: no fundamentals
(earnings growth etc.) because no verified free source exists.

Per stock: RS rating (1-99 percentile of 0.4*3m + 0.3*6m + 0.3*12m return
within the universe), Weinstein-style stage, distance from the 52-week
high, ATR%, 20-day average traded value, and which setups fire today:
  - every registered signal strategy (ma_trend_pullback, donchian_trend, ...)
  - trend_template_only: Minervini template holds (no breakout needed)
  - near_high: within 5% of the 52-week high in an uptrend
  - momentum_burst: up >= 4% on volume above the prior day's (stockbee)
  - gap_up_volume: opened >= 4% above the prior close on >= 2x volume
    (episodic-pivot style; check the news before acting)
  - oversold_uptrend: RSI(2) < 10 above the 200-day average
A setup firing is a research lead, not an instruction to buy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from ..indicators.core import add_indicators
from ..strategies import SIGNAL_STRATEGIES


@dataclass
class ScreenRow:
    symbol: str
    as_of: str
    close: float
    rs: int
    stage: str
    from_high_pct: float
    atr_pct: float
    value_cr: float
    sector: str = ""
    setups: list[str] = field(default_factory=list)
    plans: dict[str, tuple[float, float, float]] = field(default_factory=dict)


def stage(r: pd.Series, sma150_slope: float) -> str:
    c, s150 = r["close"], r["sma150"]
    if pd.isna(s150):
        return "?"
    if c > s150 and sma150_slope > 0:
        return "2 uptrend"
    if c < s150 and sma150_slope < 0:
        return "4 downtrend"
    return "3 topping" if c < s150 else "1 basing"


def screen(frames: dict[str, pd.DataFrame], as_of: Optional[date] = None,
           sector_map: Optional[dict[str, dict]] = None) -> list[ScreenRow]:
    raw = {}
    for sym, df in frames.items():
        d = df.reset_index(drop=True)
        if as_of is not None:
            d = d[d["date"].dt.date <= as_of].reset_index(drop=True)
        if len(d) < 60:
            continue
        x = add_indicators(d.iloc[-400:].reset_index(drop=True))
        raw[sym] = x
    mom = {}
    for sym, x in raw.items():
        r = x.iloc[-1]
        parts = [(0.4, r.get("ret63")), (0.3, r.get("ret126")), (0.3, r.get("ret252"))]
        if any(pd.isna(v) for _, v in parts):
            continue
        mom[sym] = sum(w * v for w, v in parts)
    order = sorted(mom, key=lambda s: mom[s])
    rs = {s: max(1, min(99, int(round(99 * (k + 1) / len(order))))) for k, s in enumerate(order)}

    rows = []
    for sym, x in raw.items():
        r = x.iloc[-1]
        prev = x.iloc[-2]
        slope = float(x["sma150"].iloc[-1] - x["sma150"].iloc[-22]) if len(x) > 22 else float("nan")
        hh = r["hh252"] if not pd.isna(r["hh252"]) else x["high"].iloc[-252:].max()
        value = float((x["close"] * x["volume"]).iloc[-20:].mean()) / 1e7
        row = ScreenRow(sym, str(r["date"].date()), round(float(r["close"]), 2), rs.get(sym, 0),
                        stage(r, slope), round(100 * (float(r["close"]) / float(max(hh, r["high"])) - 1), 1),
                        round(100 * float(r["atr14"]) / float(r["close"]), 2) if not pd.isna(r["atr14"]) else float("nan"),
                        round(value, 1), (sector_map or {}).get(sym, {}).get("sector", ""))
        for name, strat in SIGNAL_STRATEGIES.items():
            if len(d) < strat.min_bars:
                continue
            sg = strat.signals(x).iloc[-1]
            if bool(sg["signal"]):
                row.setups.append(name)
                row.plans[name] = (row.close, float(sg["stop"]), float(sg["target"]))
        c = float(r["close"])
        tt = SIGNAL_STRATEGIES["trend_template"]
        template_rules = tt.conditions(x.iloc[-1:], tt.params)[:5]      # price, stacked MAs, rising 200, 52w low/high
        if all(bool(v.fillna(False).iloc[-1]) for v, _, _ in template_rules):
            row.setups.append("trend_template_only")
        if row.stage.startswith("2") and row.from_high_pct >= -5:
            row.setups.append("near_high")
        if c / float(prev["close"]) - 1 >= 0.04 and r["volume"] > prev["volume"]:
            row.setups.append("momentum_burst")
        if float(r["open"]) / float(prev["close"]) - 1 >= 0.04 and not pd.isna(r["relvol20"]) and r["relvol20"] >= 2:
            row.setups.append("gap_up_volume")
        if not pd.isna(r["rsi2"]) and r["rsi2"] < 10 and not pd.isna(r["sma200"]) and c > r["sma200"]:
            row.setups.append("oversold_uptrend")
        rows.append(row)
    return sorted(rows, key=lambda r: (-len([s for s in r.setups]), -r.rs))


def format_screen(rows: list[ScreenRow], setup: Optional[str] = None, min_rs: int = 0, top: int = 30) -> str:
    sel = [r for r in rows if r.rs >= min_rs and (setup is None or setup in r.setups)]
    sel.sort(key=lambda r: (-(setup in r.setups if setup else len(r.setups)), -r.rs))
    lines = [f"NSE SCREEN — {len(sel)} of {len(rows)} stocks" + (f" with setup {setup}" if setup else "")
             + (f", RS >= {min_rs}" if min_rs else "") + f" (as of {rows[0].as_of if rows else '-'})",
             f"  {'symbol':12}{'close':>10}{'RS':>4}  {'stage':12}{'vs52wH':>8}{'ATR%':>6}{'₹cr/day':>9}  {'sector':18} setups"]
    for r in sel[:top]:
        lines.append(f"  {r.symbol:12}{r.close:>10.2f}{r.rs:>4}  {r.stage:12}{r.from_high_pct:>7.1f}%{r.atr_pct:>6.2f}"
                     f"{r.value_cr:>9.1f}  {r.sector[:18]:18} {', '.join(r.setups) or '-'}")
    lines.append("  RS = 1-99 rank of 3/6/12-month momentum inside THIS universe. Technical data only; "
                 "a setup is a lead to research, not advice.")
    return "\n".join(lines)
