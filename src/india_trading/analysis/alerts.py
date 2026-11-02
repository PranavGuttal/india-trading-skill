"""Price and setup alerts (adapted from day-trader-skill trader-alerts).

Rules live in a YAML file (config/alerts.yaml), e.g.:

    alerts:
      - {symbol: INFY, above: 1600}
      - {symbol: TCS, below: 3200, note: "add zone"}
      - {symbol: SBIN, change_below_pct: -3}
      - {symbol: ITC, rsi14_below: 30}
      - {symbol: RELIANCE, new_52w_high: true}
      - {symbol: HDFCBANK, cross_above: sma200}

Plus automatic alerts for every open paper position: within 1 ATR of its
stop, at/above its target, or a close-rule exit pending. Evaluated on the
latest bar (or on current prices you pass). Alerts never place orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from ..indicators.core import add_indicators

KEYS = {"symbol", "above", "below", "change_below_pct", "change_above_pct", "rsi14_below", "rsi14_above",
        "new_52w_high", "new_52w_low", "cross_above", "cross_below", "note"}
AVERAGES = ("sma20", "sma50", "sma150", "sma200")


@dataclass
class Alert:
    symbol: str
    message: str
    kind: str


def load_rules(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rules = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("alerts") or []
    for r in rules:
        bad = set(r) - KEYS
        if bad or "symbol" not in r:
            raise ValueError(f"alert rule {r}: unknown keys {sorted(bad)} or no symbol")
        for k in ("cross_above", "cross_below"):
            if k in r and r[k] not in AVERAGES:
                raise ValueError(f"alert rule {r}: {k} must be one of {', '.join(AVERAGES)}")
    return rules


def evaluate(rules: list[dict], frames: dict[str, pd.DataFrame], prices: Optional[dict[str, float]] = None,
             positions: Optional[list] = None) -> list[Alert]:
    prices = prices or {}
    out: list[Alert] = []
    cache: dict[str, pd.DataFrame] = {}

    def ind(sym):
        if sym not in cache:
            cache[sym] = add_indicators(frames[sym].iloc[-300:].reset_index(drop=True))
        return cache[sym]

    for r in rules:
        sym = str(r["symbol"]).upper()
        if sym not in frames:
            out.append(Alert(sym, "no data for this symbol (run data-fetch)", "error"))
            continue
        x = ind(sym)
        last, prev = x.iloc[-1], x.iloc[-2]
        px = float(prices.get(sym, last["close"]))
        note = f" — {r['note']}" if r.get("note") else ""
        chg = 100 * (px / float(prev["close"]) - 1) if sym in prices else 100 * (float(last["close"]) / float(prev["close"]) - 1)
        checks = [
            ("above", lambda v: px >= v, lambda v: f"price ₹{px:,.2f} at/above ₹{v:,.2f}"),
            ("below", lambda v: px <= v, lambda v: f"price ₹{px:,.2f} at/below ₹{v:,.2f}"),
            ("change_below_pct", lambda v: chg <= v, lambda v: f"day change {chg:+.2f}% <= {v}%"),
            ("change_above_pct", lambda v: chg >= v, lambda v: f"day change {chg:+.2f}% >= {v}%"),
            ("rsi14_below", lambda v: last["rsi14"] < v, lambda v: f"RSI14 {last['rsi14']:.1f} < {v}"),
            ("rsi14_above", lambda v: last["rsi14"] > v, lambda v: f"RSI14 {last['rsi14']:.1f} > {v}"),
            ("new_52w_high", lambda v: v and px >= x["high"].iloc[-252:].max(), lambda v: "new 52-week high"),
            ("new_52w_low", lambda v: v and px <= x["low"].iloc[-252:].min(), lambda v: "new 52-week low"),
            ("cross_above", lambda v: prev["close"] <= prev[v] and px > last[v], lambda v: f"crossed above {v.upper()}"),
            ("cross_below", lambda v: prev["close"] >= prev[v] and px < last[v], lambda v: f"crossed below {v.upper()}"),
        ]
        for key, test, msg in checks:
            if key in r and bool(test(r[key])):
                out.append(Alert(sym, msg(r[key]) + note, key))
    for pos in positions or []:
        if pos.symbol not in frames:
            continue
        x = ind(pos.symbol)
        px = float(prices.get(pos.symbol, x["close"].iloc[-1]))
        atr = float(x["atr14"].iloc[-1])
        if pos.stop and px - pos.stop <= atr:
            out.append(Alert(pos.symbol, f"paper position within 1 ATR of its stop (₹{px:,.2f} vs stop ₹{pos.stop:,.2f})", "position"))
        if pos.target and px >= pos.target:
            out.append(Alert(pos.symbol, f"paper position at/above target ₹{pos.target:,.2f}", "position"))
    return out


def format_alerts(alerts: list[Alert], as_of: str) -> str:
    if not alerts:
        return f"ALERTS as of {as_of}: none triggered."
    return "\n".join([f"ALERTS as of {as_of}: {len(alerts)} triggered (no orders are placed)"] +
                     [f"  [{a.kind}] {a.symbol}: {a.message}" for a in alerts])
