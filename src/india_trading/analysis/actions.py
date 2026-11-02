"""Corporate actions (dividends, splits) from the Yahoo chart feed's events.

data-fetch saves them to <data_dir>/events/SYMBOL.json. Yahoo reports past
ex-dates only; it does not give announced FUTURE ex-dates or results dates.
Prices are split-adjusted, NOT dividend-adjusted: a backtest return
excludes dividends (they are summarised here instead).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class ActionsSummary:
    symbol: str
    as_of: str
    close: float
    dividends_12m: float
    yield_12m_pct: float
    dividends_prev_12m: float
    last_dividend: str
    splits: list[str]
    recent: list[dict]


def summarise(symbol: str, df: pd.DataFrame, events: list[dict]) -> ActionsSummary:
    last = pd.Timestamp(df["date"].iloc[-1])
    close = float(df["close"].iloc[-1])
    div = [e for e in events if e["type"] == "dividend"]
    y1 = sum(e["amount"] for e in div if pd.Timestamp(e["date"]) > last - pd.Timedelta(days=365))
    y0 = sum(e["amount"] for e in div
             if last - pd.Timedelta(days=730) < pd.Timestamp(e["date"]) <= last - pd.Timedelta(days=365))
    ld = f"{div[-1]['date']} ₹{div[-1]['amount']}" if div else "none on record"
    return ActionsSummary(symbol, str(last.date()), round(close, 2), round(y1, 2), round(100 * y1 / close, 2),
                          round(y0, 2), ld, [f"{e['date']} {e['ratio']}" for e in events if e["type"] == "split"],
                          [e for e in events if pd.Timestamp(e["date"]) > last - pd.Timedelta(days=90)])


def format_actions(rows: list[ActionsSummary]) -> str:
    lines = ["CORPORATE ACTIONS (Yahoo Finance events, unofficial; past ex-dates only)",
             f"  {'symbol':12}{'close':>10}{'div 12m':>9}{'yield':>7}{'prev 12m':>9}  last dividend / splits"]
    for r in sorted(rows, key=lambda r: -r.yield_12m_pct):
        trend = "" if not r.dividends_prev_12m else (" ↓cut" if r.dividends_12m < 0.9 * r.dividends_prev_12m else
                                                     " ↑" if r.dividends_12m > 1.1 * r.dividends_prev_12m else "")
        lines.append(f"  {r.symbol:12}{r.close:>10.2f}{r.dividends_12m:>9.2f}{r.yield_12m_pct:>6.2f}%{r.dividends_prev_12m:>9.2f}"
                     f"  {r.last_dividend}{trend}" + (f" | splits {', '.join(r.splits)}" if r.splits else ""))
    lines.append("  Upcoming ex-dates, results dates and bonus announcements are not in this feed: "
                 "check the company's NSE announcements before trading around them.")
    return "\n".join(lines)
