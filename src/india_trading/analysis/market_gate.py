"""Market gate: no NEW entries while Nifty 50 closes at or below its 200-day
average. Tested in the strategy lab (docs/STRATEGY_LAB.md, "Loss
reduction"): on two universes and both halves of 2017-2026 it lowered
drawdowns, losing months and charges for every swing strategy. It only ever
removes entries; exits are never gated.

Fails closed: no Nifty 50 data, too little history, or data older than
`max_bar_age_days` business days -> "unknown", which the risk manager treats
as a block.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..market_data.csv_source import DataError, load_csv

SMA_DAYS = 200


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> Optional[pd.DataFrame]:
    try:
        df, rep, _ = load_csv(path, "NIFTY50")
    except DataError:
        return None
    if not rep.ok:
        return None
    df = df[["date", "close"]].copy()
    df["sma"] = df["close"].rolling(SMA_DAYS, min_periods=SMA_DAYS).mean()
    return df


def index_frame(indices_dir: str | Path) -> Optional[pd.DataFrame]:
    p = Path(indices_dir) / "NIFTY50.csv"
    if not p.exists():
        return None
    return _load(str(p), p.stat().st_mtime)


def market_ok(indices_dir: str | Path, on: date, max_age_days: int = 5) -> tuple[Optional[bool], str]:
    """(True/False/None=unknown, explanation) for decisions made on date `on`."""
    df = index_frame(indices_dir)
    if df is None:
        return None, f"market gate: no valid Nifty 50 data in {indices_dir} (run `data-fetch --indices`)"
    n = int(df["date"].searchsorted(pd.Timestamp(on), side="right"))
    if n == 0 or pd.isna(df["sma"].iloc[n - 1]):
        return None, f"market gate: not enough Nifty 50 history before {on}"
    row = df.iloc[n - 1]
    age = int(np.busday_count(row["date"].date(), on))
    if age > max_age_days:
        return None, f"market gate: latest Nifty 50 bar {row['date'].date()} is {age} business days old (refresh data)"
    c, m = float(row["close"]), float(row["sma"])
    if c > m:
        return True, f"market gate open: Nifty 50 {c:,.0f} > 200-day average {m:,.0f} ({row['date'].date()})"
    return False, (f"market gate: Nifty 50 {c:,.0f} is below its 200-day average {m:,.0f} on {row['date'].date()} — "
                   "no new entries (tested to reduce losses)")
