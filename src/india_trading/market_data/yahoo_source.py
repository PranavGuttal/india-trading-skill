"""Daily NSE candles from Yahoo Finance's public chart endpoint (SYMBOL.NS).

Verified 2026-11-01 from this machine: returns NSE (exchange "NSI", IST)
daily open/high/low/close/volume. It is free and UNOFFICIAL: meant for
personal use, may lag or have gaps, and can change without notice. NSE's own
site returned 403 to scripts and is not used. Prices are split-adjusted by
Yahoo; dividends are not adjusted. Every row is labelled with its source.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from .calendar import IST, NSECalendar
from .csv_source import DataError, validate_bars

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?{qs}"
SOURCE = "yahoo-finance (unofficial)"
_UA = "Mozilla/5.0 (india-trading-skill; personal research)"


def _http_get(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (fixed https host)
        return r.read()


def parse_chart(payload: dict, symbol: str, now: Optional[datetime] = None) -> pd.DataFrame:
    """Yahoo v8 chart JSON -> date,open,high,low,close,volume,source. Drops
    rows with missing values and today's bar while the session is still open."""
    err = (payload.get("chart") or {}).get("error")
    if err:
        raise DataError(f"Yahoo error for {symbol}: {err.get('description') or err}")
    res = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise DataError(f"no data from Yahoo for {symbol}.NS (wrong symbol?)")
    meta = res.get("meta") or {}
    if meta.get("exchangeName") not in ("NSI", None) or meta.get("currency") not in ("INR", None):
        raise DataError(f"{symbol}.NS is not an NSE INR listing (exchange {meta.get('exchangeName')})")
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({
        "date": pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(IST).tz_localize(None).normalize(),
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"], "volume": q["volume"],
    }).dropna()
    df = df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    now = now or datetime.now(IST)
    if len(df) and df["date"].iloc[-1].date() == now.date() and now.time() < dtime(15, 30):
        df = df.iloc[:-1]                      # today's bar is not final yet
    for c in ["open", "high", "low", "close"]:
        df[c] = df[c].astype(float).round(2)
    df["volume"] = df["volume"].astype("int64")
    df["source"] = SOURCE
    return df


def fetch(symbol: str, years: int = 5, http_get: Callable[[str], bytes] = _http_get,
          now: Optional[datetime] = None) -> pd.DataFrame:
    sym = symbol.upper().strip()
    if not sym.replace("-", "").replace("&", "").isalnum():
        raise DataError(f"bad NSE symbol {symbol!r}")
    qs = urllib.parse.urlencode({"range": f"{int(years)}y", "interval": "1d"})
    try:
        payload = json.loads(http_get(URL.format(sym=urllib.parse.quote(sym), qs=qs)))
    except DataError:
        raise
    except Exception as e:
        raise DataError(f"download failed for {sym}: {e}") from e
    return parse_chart(payload, sym, now)


def fetch_to_csv(symbols: list[str], out_dir: str | Path, years: int = 5,
                 calendar: Optional[NSECalendar] = None, pause_s: float = 1.0,
                 http_get: Callable[[str], bytes] = _http_get) -> list[tuple[str, str, list[str]]]:
    """Returns (symbol, status, messages) per symbol. Writes only validated data."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, sym in enumerate(symbols):
        if i:
            time.sleep(pause_s)                # be polite to a free endpoint
        try:
            df = fetch(sym, years, http_get)
            rep = validate_bars(df, calendar)
            if not rep.ok:
                results.append((sym.upper(), "INVALID", rep.errors))
                continue
            path = out / f"{sym.upper()}.csv"
            df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_csv(path, index=False)
            msg = [f"{len(df)} bars {df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()} → {path}"]
            results.append((sym.upper(), "OK", msg + rep.warnings))
        except DataError as e:
            results.append((sym.upper(), "ERROR", [str(e)]))
    return results
