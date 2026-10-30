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
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from ..indicators.core import add_indicators
from ..market_data.csv_source import last_bar_as_of
from ..models import TradeProposal

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


def evaluate(df: pd.DataFrame, symbol: str, data_source: str, p: Params = PARAMS, indicators: pd.DataFrame | None = None) -> TradeProposal:
    """Decide using ONLY the rows given (caller must not pass future rows)."""
    as_of = last_bar_as_of(df)
    base = dict(symbol=symbol, strategy=NAME, strategy_version=VERSION, as_of=as_of, data_source=data_source)
    if len(df) < p.min_bars:
        return TradeProposal(decision="NO_TRADE", reasons=[f"only {len(df)} bars; need {p.min_bars}"], **base)
    x = indicators if indicators is not None else add_indicators(df)
    r = x.iloc[-1]
    needed = ["sma20", "sma50", "rsi14", "atr14", "relvol20", "support20"]
    if r[needed].isna().any():
        return TradeProposal(decision="NO_TRADE", reasons=["indicators not yet available"], **base)

    close, atr_ = float(r["close"]), float(r["atr14"])
    why, against = [], []
    checks = [
        (close >= p.min_price, f"close ₹{close:.2f} >= ₹{p.min_price}", f"close ₹{close:.2f} below ₹{p.min_price}"),
        (close > r["sma50"] and r["sma20"] > r["sma50"], "uptrend: close>SMA50 and SMA20>SMA50", "no uptrend (SMA20/SMA50)"),
        (abs(close - r["sma20"]) <= p.pullback_atr * atr_, f"within {p.pullback_atr} ATR of SMA20", "extended from SMA20"),
        (p.rsi_low <= r["rsi14"] <= p.rsi_high, f"RSI {r['rsi14']:.1f} in [{p.rsi_low},{p.rsi_high}]", f"RSI {r['rsi14']:.1f} outside [{p.rsi_low},{p.rsi_high}]"),
        (r["relvol20"] >= p.min_relvol, f"rel. volume {r['relvol20']:.2f} >= {p.min_relvol}", f"rel. volume {r['relvol20']:.2f} < {p.min_relvol}"),
    ]
    for ok, yes, no in checks:
        (why if ok else against).append(yes if ok else no)
    if r["macd_hist"] < 0:
        against.append("MACD histogram negative (momentum fading)")
    if against and any(not ok for ok, _, _ in checks):
        return TradeProposal(decision="NO_TRADE", reasons=[a for a in against], contra=why, **base)

    entry = close
    stop = max(entry - p.stop_atr * atr_, float(r["support20"]) - 0.1 * atr_)
    stop = min(stop, entry - 1.0 * atr_)
    target = entry + p.target_r * (entry - stop)
    return TradeProposal(
        decision="TRADE", reasons=why, contra=against, entry=round(entry, 2), stop=round(stop, 2),
        target=round(target, 2), max_hold_days=p.max_hold_days, **base,
    )


def describe() -> dict:
    return {"name": NAME, "version": VERSION, "params": asdict(PARAMS)}
