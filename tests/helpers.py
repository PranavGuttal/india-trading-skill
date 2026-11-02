"""Synthetic OHLCV for tests. NOT market data."""
from __future__ import annotations

import numpy as np
import pandas as pd


def walk(n=400, start=100.0, drift=0.0008, vol=0.012, seed=1, begin="2022-01-03", volume=200_000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    close = start * np.exp(np.cumsum(r))
    open_ = np.concatenate([[start], close[:-1]]) * (1 + rng.normal(0, vol / 4, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = (volume * (1 + np.abs(rng.normal(0, 0.3, n)))).astype("int64")
    return pd.DataFrame({"date": pd.bdate_range(begin, periods=n), "open": open_.round(2), "high": high.round(2),
                         "low": low.round(2), "close": close.round(2), "volume": v})


def write(df: pd.DataFrame, folder, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    df.assign(date=df["date"].dt.strftime("%Y-%m-%d"), source="SYNTHETIC test data").to_csv(folder / f"{name}.csv", index=False)
