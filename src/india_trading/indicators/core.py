"""Deterministic technical indicators. Each value at row t uses rows <= t only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    if n < 1:
        raise ValueError("n must be >= 1")
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    """EMA seeded with the SMA of the first n values (common charting convention)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(s) < n:
        return out
    alpha = 2 / (n + 1)
    vals = s.to_numpy(dtype=float)
    prev = vals[:n].mean()
    out.iloc[n - 1] = prev
    for i in range(n, len(vals)):
        prev = alpha * vals[i] + (1 - alpha) * prev
        out.iloc[i] = prev
    return out


def _wilder(values: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < n:
        return out
    prev = values[:n].mean()
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = (prev * (n - 1) + values[i]) / n
        out[i] = prev
    return out


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI. First value at index n."""
    d = close.diff().to_numpy(dtype=float)[1:]
    gains = np.where(d > 0, d, 0.0)
    losses = np.where(d < 0, -d, 0.0)
    ag, al = _wilder(gains, n), _wilder(losses, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        r = 100 - 100 / (1 + rs)
    r = np.where((al == 0) & ~np.isnan(ag), 100.0, r)
    r = np.where((al == 0) & (ag == 0), 50.0, r)
    return pd.Series(np.concatenate([[np.nan], r]), index=close.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = pd.Series(np.nan, index=close.index)
    valid = line.dropna()
    if len(valid) >= signal:
        sig.loc[valid.index] = ema(valid.reset_index(drop=True), signal).to_numpy()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return pd.Series(_wilder(true_range(df).to_numpy(dtype=float), n), index=df.index)


def relative_volume(volume: pd.Series, n: int = 20) -> pd.Series:
    """Today's volume / mean of the PREVIOUS n days (excludes today)."""
    base = volume.shift(1).rolling(n, min_periods=n).mean()
    return volume / base


def vwap(intraday: pd.DataFrame) -> pd.Series:
    """Session VWAP for intraday bars of ONE session (needs high, low, close, volume)."""
    tp = (intraday["high"] + intraday["low"] + intraday["close"]) / 3
    cv = intraday["volume"].cumsum()
    return (tp * intraday["volume"]).cumsum() / cv.replace(0, np.nan)


def support_resistance(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Prior n-day low/high (excludes the current bar)."""
    return pd.DataFrame({
        "support": df["low"].shift(1).rolling(n, min_periods=n).min(),
        "resistance": df["high"].shift(1).rolling(n, min_periods=n).max(),
    })


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sma20"] = sma(out["close"], 20)
    out["sma50"] = sma(out["close"], 50)
    out["rsi14"] = rsi(out["close"], 14)
    out["atr14"] = atr(out, 14)
    out["relvol20"] = relative_volume(out["volume"], 20)
    sr = support_resistance(out, 20)
    out["support20"], out["resistance20"] = sr["support"], sr["resistance"]
    m = macd(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = m["macd"], m["signal"], m["hist"]
    return out
