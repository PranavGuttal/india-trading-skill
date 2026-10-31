"""Normalise a daily-candle CSV you exported (NSE historical data page, Groww
chart data, etc.) into this toolkit's format:

    date,open,high,low,close,volume,source

Header names are matched case-insensitively against common spellings; numbers
with thousands separators are cleaned; rows are sorted and de-duplicated. The
result is VALIDATED before it is written, and nothing is invented: a column
that cannot be found is an error, not a guess.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .calendar import NSECalendar
from .csv_source import DataError, validate_bars

ALIASES = {
    "date": ["date", "timestamp", "trade date", "ch_timestamp", "datetime", "time"],
    "open": ["open", "open price", "ch_opening_price", "opening price"],
    "high": ["high", "high price", "ch_trade_high_price"],
    "low": ["low", "low price", "ch_trade_low_price"],
    "close": ["close", "close price", "ch_closing_price", "closing price", "ltp"],
    "volume": ["volume", "total traded quantity", "ch_tot_traded_qty", "no. of shares", "qty"],
}
SERIES_COLS = ["series", "ch_series"]


def _key(c: str) -> str:
    return re.sub(r"\s+", " ", str(c).replace("﻿", "").strip().lower())


def normalise(raw: pd.DataFrame, source: str, series: str = "EQ") -> pd.DataFrame:
    cols = {_key(c): c for c in raw.columns}
    picked = {}
    for want, names in ALIASES.items():
        hit = next((cols[n] for n in names if n in cols), None)
        if hit is None:
            raise DataError(f"no column for {want!r}; headers were {list(raw.columns)}")
        picked[want] = hit
    df = raw.copy()
    ser = next((cols[n] for n in SERIES_COLS if n in cols), None)
    if ser is not None:
        df = df[df[ser].astype(str).str.strip().str.upper() == series.upper()]
    out = pd.DataFrame({k: df[v] for k, v in picked.items()})
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", "").str.strip(), errors="coerce")
    out["date"] = pd.to_datetime(out["date"], errors="coerce", dayfirst=True, format="mixed")
    if out["date"].isna().any():
        raise DataError("some dates could not be parsed")
    if out["date"].dt.tz is not None:
        out["date"] = out["date"].dt.tz_localize(None)
    out["date"] = out["date"].dt.normalize()
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    out["source"] = source
    return out


def import_csv(src: str | Path, symbol: str, out_dir: str | Path, source: str,
               calendar: NSECalendar | None = None, series: str = "EQ") -> tuple[Path, list[str]]:
    raw = pd.read_csv(src)
    df = normalise(raw, source, series)
    rep = validate_bars(df, calendar)
    if not rep.ok:
        raise DataError("; ".join(rep.errors))
    out = Path(out_dir) / f"{symbol.upper()}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_csv(out, index=False)
    return out, rep.warnings
