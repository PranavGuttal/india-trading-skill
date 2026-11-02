"""Strategy 1: moving-average trend + pullback, long only, daily bars.

Transparent rules (all parameters explicit, see PARAMS):

Eligible: NSE cash equity, close >= min_price, >= 60 valid bars.
ENTRY (evaluated on the close of bar t, order for next session):
  1. close > SMA50 and SMA20 > SMA50                (uptrend)
  2. close within pullback_atr * ATR14 of SMA20     (not extended)
  3. rsi_low <= RSI14 <= rsi_high                   (not overbought/weak)
  4. relative volume >= min_relvol                  (some participation)
STOP:   max(entry - stop_atr * ATR14, support20 - 0.1*ATR14)  -> the tighter of the two
        but never closer than 1*ATR14 below entry
TARGET: entry + target_r * (entry - stop)
EXIT:   stop, target, close < SMA50, or max_hold_days
ABSTAIN (NO_TRADE) when any rule fails or data is insufficient.
Costs/slippage are NOT assumed here; risk manager and backtester apply them.

Real-data result (docs/BACKTESTING.md): NO EDGE after charges on 20 large
NSE stocks, 2021-2026. Kept as the reference strategy.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import ExitPolicy, Strategy

NAME = "ma_trend_pullback"
VERSION = "1.0.0"


@dataclass(frozen=True)
class Params:
    min_bars: int = 60
    min_price: float = 20.0
    pullback_atr: float = 1.0
    rsi_low: float = 40.0
    rsi_high: float = 65.0
    min_relvol: float = 0.8
    stop_atr: float = 2.0
    target_r: float = 2.0
    max_hold_days: int = 10


PARAMS = Params()


def _conditions(x: pd.DataFrame, p: Params):
    c, a = x["close"], x["atr14"]
    return [
        (c >= p.min_price, f"close ₹{c.iloc[-1]:.2f} >= ₹{p.min_price}", f"close ₹{c.iloc[-1]:.2f} below ₹{p.min_price}"),
        ((c > x["sma50"]) & (x["sma20"] > x["sma50"]), "uptrend: close>SMA50 and SMA20>SMA50", "no uptrend (SMA20/SMA50)"),
        ((c - x["sma20"]).abs() <= p.pullback_atr * a, f"within {p.pullback_atr} ATR of SMA20", "extended from SMA20"),
        ((x["rsi14"] >= p.rsi_low) & (x["rsi14"] <= p.rsi_high),
         f"RSI {x['rsi14'].iloc[-1]:.1f} in [{p.rsi_low},{p.rsi_high}]",
         f"RSI {x['rsi14'].iloc[-1]:.1f} outside [{p.rsi_low},{p.rsi_high}]"),
        (x["relvol20"] >= p.min_relvol, f"rel. volume {x['relvol20'].iloc[-1]:.2f} >= {p.min_relvol}",
         f"rel. volume {x['relvol20'].iloc[-1]:.2f} < {p.min_relvol}"),
    ]


def _levels(x: pd.DataFrame, p: Params):
    c, a = x["close"], x["atr14"]
    stop = np.maximum(c - p.stop_atr * a, x["support20"] - 0.1 * a)
    stop = np.minimum(stop, c - 1.0 * a)
    return stop, c + p.target_r * (c - stop), -(c - x["sma20"]).abs() / a


def _notes(r: pd.Series) -> list[str]:
    return ["MACD histogram negative (momentum fading)"] if r.get("macd_hist", 0) < 0 else []


STRATEGY = Strategy(
    name=NAME, version=VERSION, params=PARAMS, min_bars=PARAMS.min_bars,
    summary="Buy a pullback to the 20-day average inside an uptrend; fixed 2R target, 10-day max hold.",
    origin="classic swing-trading pullback (both reference repos use pullback scans)",
    exit=ExitPolicy(take_profit=True, close_below="sma50", max_hold_days=PARAMS.max_hold_days),
    conditions=_conditions, levels=_levels, notes=_notes,
    required=("sma20", "sma50", "rsi14", "atr14", "relvol20", "support20"),
)


def evaluate(df: pd.DataFrame, symbol: str, data_source: str, p: Params = PARAMS,
             indicators: pd.DataFrame | None = None):
    """Decide using ONLY the rows given (caller must not pass future rows)."""
    return STRATEGY.evaluate(df, symbol, data_source, indicators=indicators)


def describe() -> dict:
    return STRATEGY.describe()
