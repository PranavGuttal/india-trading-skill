"""Trend-following and mean-reversion signal strategies (long only, daily).

Parameters are TEXTBOOK values fixed before testing on NSE data, not fitted
to it. Results: docs/STRATEGY_LAB.md.

donchian_trend      55-day breakout in a long-term uptrend; trails a 3-ATR
                    chandelier stop, exits on a 20-day low. (Turtle-style
                    breakout; tradermonty breakout-trade-planner idea.)
trend_template      Minervini-style trend template + tight 20-day base +
                    volume breakout. (tradermonty vcp-screener / canslim idea.)
rsi2_reversion      Connors RSI(2) < 10 dip inside a 200-day uptrend; exits
                    on a close above the 5-day average. (day-trader
                    "oversold bounce" scan idea.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import ExitPolicy, Strategy


# ---------------------------------------------------------------- Donchian trend
@dataclass(frozen=True)
class DonchianParams:
    min_price: float = 20.0
    stop_atr: float = 2.0
    plan_r: float = 3.0
    trail_atr: float = 3.0
    max_hold_days: int = 250


def _donchian_conditions(x, p: DonchianParams):
    c = x["close"]
    return [
        (c >= p.min_price, f"close >= ₹{p.min_price}", f"close below ₹{p.min_price}"),
        (c > x["hh55"], "close above the prior 55-day high (breakout)", "no 55-day breakout"),
        ((c > x["sma200"]) & (x["sma50"] > x["sma200"]), "long-term uptrend (close>SMA200, SMA50>SMA200)",
         "not in a long-term uptrend"),
    ]


def _donchian_levels(x, p: DonchianParams):
    c, a = x["close"], x["atr14"]
    stop = c - p.stop_atr * a
    return stop, c + p.plan_r * (c - stop), x["ret126"]


DONCHIAN = Strategy(
    name="donchian_trend", version="1.0.0", params=DonchianParams(), min_bars=253,
    summary="Buy a 55-day high in a long-term uptrend; let winners run with a 3-ATR trailing stop.",
    origin="Turtle-style Donchian breakout; tradermonty breakout-trade-planner",
    exit=ExitPolicy(take_profit=False, trail_atr=3.0, close_below="ll20", max_hold_days=250),
    conditions=_donchian_conditions, levels=_donchian_levels,
    required=("hh55", "ll20", "sma50", "sma200", "atr14", "ret126"),
)


# ---------------------------------------------------------------- Trend template
@dataclass(frozen=True)
class TemplateParams:
    min_price: float = 20.0
    above_low: float = 1.30          # >= 30% above the 52-week low
    near_high: float = 0.75          # within 25% of the 52-week high
    max_base_depth: float = 0.15     # prior 20-day range <= 15% of its high
    min_relvol: float = 1.5
    max_stop_pct: float = 0.08
    plan_r: float = 3.0
    trail_atr: float = 3.0
    max_hold_days: int = 120


def _template_conditions(x, p: TemplateParams):
    c = x["close"]
    depth = (x["hh20"] - x["ll20"]) / x["hh20"]
    return [
        (c >= p.min_price, f"close >= ₹{p.min_price}", f"close below ₹{p.min_price}"),
        ((c > x["sma50"]) & (x["sma50"] > x["sma150"]) & (x["sma150"] > x["sma200"]),
         "stacked uptrend: close > SMA50 > SMA150 > SMA200", "averages not stacked (close>50>150>200)"),
        (x["sma200"] > x["sma200_21ago"], "SMA200 rising for a month", "SMA200 not rising"),
        (c >= p.above_low * x["ll252"], f">= {p.above_low - 1:.0%} above the 52-week low", "too close to the 52-week low"),
        (c >= p.near_high * x["hh252"], f"within {1 - p.near_high:.0%} of the 52-week high", "too far below the 52-week high"),
        (depth <= p.max_base_depth, f"tight base (20-day range <= {p.max_base_depth:.0%})", "base too loose"),
        (c > x["hh20"], "breakout above the 20-day base", "no base breakout"),
        (x["relvol20"] >= p.min_relvol, f"breakout volume >= {p.min_relvol}x average", "breakout volume too low"),
    ]


def _template_levels(x, p: TemplateParams):
    c, a = x["close"], x["atr14"]
    stop = np.maximum(x["ll10"] - 0.1 * a, c * (1 - p.max_stop_pct))
    stop = np.minimum(stop, c - a)
    return stop, c + p.plan_r * (c - stop), x["ret126"]


TEMPLATE = Strategy(
    name="trend_template", version="1.0.0", params=TemplateParams(), min_bars=253,
    summary="Leader in a stacked uptrend breaks out of a tight base on volume; stop under the base, trail 3 ATR.",
    origin="Minervini trend template / VCP; tradermonty vcp-screener and canslim-screener",
    exit=ExitPolicy(take_profit=False, trail_atr=3.0, close_below="sma50", max_hold_days=120),
    conditions=_template_conditions, levels=_template_levels,
    required=("sma50", "sma150", "sma200", "sma200_21ago", "hh20", "ll20", "ll10", "hh252", "ll252", "relvol20", "atr14"),
)


# ---------------------------------------------------------------- RSI(2) reversion
@dataclass(frozen=True)
class Rsi2Params:
    min_price: float = 20.0
    rsi_max: float = 10.0
    stop_atr: float = 2.5
    plan_r: float = 1.5
    max_hold_days: int = 10


def _rsi2_conditions(x, p: Rsi2Params):
    c = x["close"]
    return [
        (c >= p.min_price, f"close >= ₹{p.min_price}", f"close below ₹{p.min_price}"),
        (c > x["sma200"], "above the 200-day average", "below the 200-day average"),
        (x["rsi2"] < p.rsi_max, f"RSI(2) {x['rsi2'].iloc[-1]:.1f} < {p.rsi_max} (short-term oversold)",
         f"RSI(2) {x['rsi2'].iloc[-1]:.1f} not oversold"),
    ]


def _rsi2_levels(x, p: Rsi2Params):
    c, a = x["close"], x["atr14"]
    stop = c - p.stop_atr * a
    return stop, c + p.plan_r * (c - stop), -x["rsi2"]


RSI2 = Strategy(
    name="rsi2_reversion", version="1.0.0", params=Rsi2Params(), min_bars=201,
    summary="Buy a sharp 1-3 day dip in a stock above its 200-day average; sell on the first close above the 5-day average.",
    origin="Connors RSI(2); day-trader-skill oversold-bounce scan",
    exit=ExitPolicy(take_profit=False, close_above="sma5", max_hold_days=10),
    conditions=_rsi2_conditions, levels=_rsi2_levels,
    required=("sma5", "sma200", "rsi2", "atr14"),
)
