"""Generate SYNTHETIC daily OHLCV CSVs for offline testing and demos.

These are NOT real market prices. Every row carries source=SYNTHETIC.
Use real, adjusted NSE data (see docs/DATA_SOURCES.md) for any real research.

    python scripts/make_sample_data.py --out data/sample
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SPECS = {
    # symbol: (start price, drift per day, vol per day, avg volume)
    "SYNTH_TREND": (180.0, 0.0008, 0.016, 900_000),
    "SYNTH_CHOP": (45.0, 0.0000, 0.022, 3_000_000),
    "SYNTH_LARGE": (1450.0, 0.0004, 0.013, 2_000_000),
}


def make(symbol: str, start: float, mu: float, sigma: float, vol: int, days: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=days)
    regime = np.repeat(rng.choice([-1.0, 0.5, 1.5], size=days // 60 + 1), 60)[:days]
    rets = mu * regime + sigma * rng.standard_normal(days)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]]) * np.exp(0.003 * rng.standard_normal(days))
    hi = np.maximum(open_, close) * (1 + np.abs(0.008 * rng.standard_normal(days)))
    lo = np.minimum(open_, close) * (1 - np.abs(0.008 * rng.standard_normal(days)))
    v = (vol * np.exp(0.35 * rng.standard_normal(days))).astype(int)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"), "open": open_.round(2), "high": hi.round(2),
        "low": lo.round(2), "close": close.round(2), "volume": v, "source": "SYNTHETIC",
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--days", type=int, default=750)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i, (sym, (p, mu, sig, vol)) in enumerate(SPECS.items()):
        make(sym, p, mu, sig, vol, a.days, a.seed + i).to_csv(out / f"{sym}.csv", index=False)
        print(f"wrote {out / (sym + '.csv')} (SYNTHETIC)")


if __name__ == "__main__":
    main()
