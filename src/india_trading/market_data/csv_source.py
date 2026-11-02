"""Daily OHLCV from local CSV files, with strict validation.

Expected file: <data_dir>/<SYMBOL>.csv with columns
    date,open,high,low,close,volume[,source]
Dates are trading days (IST). Prices should be split/bonus-adjusted; if they
are not, the validator flags suspicious one-day jumps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import IST, NSECalendar

REQUIRED = ["date", "open", "high", "low", "close", "volume"]


class DataError(ValueError):
    pass


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def bad_ticks(df: pd.DataFrame, threshold: float = 0.4) -> pd.Series:
    """Rows whose open AND close are >= threshold away from the median close
    of the surrounding 7 bars: a 1-3 bar spike that reverts (e.g. a feed
    printing 1/10th of the price). A real move that persists shifts the
    median with it and is not flagged."""
    if len(df) < 7:
        return pd.Series(False, index=df.index)
    med = df["close"].rolling(7, center=True, min_periods=4).median()
    return ((df["close"] / med - 1).abs() >= threshold) & ((df["open"] / med - 1).abs() >= threshold)


def validate_bars(df: pd.DataFrame, calendar: NSECalendar | None = None, jump_pct: float = 0.25) -> ValidationReport:
    errors, warnings = [], []
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return ValidationReport(False, [f"missing columns: {missing}"])
    if df.empty:
        return ValidationReport(False, ["no rows"])
    if df["date"].duplicated().any():
        errors.append("duplicate dates")
    if not df["date"].is_monotonic_increasing:
        errors.append("dates are not in increasing order")
    num = df[["open", "high", "low", "close", "volume"]]
    if num.isna().any().any():
        errors.append("missing values in OHLCV")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        errors.append("non-positive prices")
    if (df["volume"] < 0).any():
        errors.append("negative volume")
    bad = (df["high"] < df[["open", "close", "low"]].max(axis=1)) | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    if bad.any():
        errors.append(f"{int(bad.sum())} rows where high/low do not contain open/close")
    if not errors:
        ticks = bad_ticks(df)
        if ticks.any():
            errors.append(f"{int(ticks.sum())} bad tick(s) (price spikes that revert), e.g. "
                          f"{pd.Timestamp(df.loc[ticks, 'date'].iloc[0]).date()}; re-fetch or remove those rows")
    if not errors:
        rets = df["close"].pct_change().abs()
        jumps = df.loc[rets > jump_pct, "date"]
        if len(jumps):
            warnings.append(f"{len(jumps)} one-day moves > {jump_pct:.0%} (unadjusted split/bonus?) e.g. {jumps.iloc[0]}")
        if calendar is not None:
            days = pd.to_datetime(df["date"]).dt.date
            non_trading = [d for d in days if not calendar.is_trading_day(d)]
            if non_trading:
                warnings.append(f"{len(non_trading)} rows on weekends/holidays, e.g. {non_trading[0]}")
            years = {d.year for d in days}
            unverified = sorted(y for y in years if not calendar.covers(y))
            if unverified:
                warnings.append(f"holiday list not verified for years {unverified}; missing-day check limited")
    return ValidationReport(not errors, errors, warnings)


def load_csv(path: str | Path, symbol: str | None = None, calendar: NSECalendar | None = None) -> tuple[pd.DataFrame, ValidationReport, str]:
    p = Path(path)
    if not p.exists():
        raise DataError(f"no data file at {p}")
    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]
    source = "csv:" + p.name
    if "source" in df.columns:
        srcs = df["source"].dropna().unique()
        if len(srcs):
            source = f"csv:{p.name} ({', '.join(map(str, srcs))})"
        df = df.drop(columns=["source"])
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if df["date"].isna().any():
            raise DataError("unparseable dates in " + p.name)
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    rep = validate_bars(df, calendar)
    return df.reset_index(drop=True), rep, source


def last_bar_as_of(df: pd.DataFrame) -> datetime:
    d = pd.Timestamp(df["date"].iloc[-1]).date()
    return datetime.combine(d, time(15, 30), tzinfo=IST)


def is_stale(df: pd.DataFrame, today: date, max_age_days: int) -> bool:
    last = pd.Timestamp(df["date"].iloc[-1]).date()
    return int(np.busday_count(last, today)) > max_age_days
