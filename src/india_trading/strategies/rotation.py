"""Momentum rotation (portfolio strategy), long only, monthly.

On the last trading day of each month, rank the universe by risk-adjusted
momentum: 0.5 * 6-month return / volatility + 0.5 * 12-month return /
volatility (volatility = annualised stdev of daily returns, 252 days).
Only stocks above their 200-day average are eligible (absolute momentum).
Hold the top `top_n` in equal weight, keep a holding while its rank is
within `hold_rank` (cuts turnover and charges), and go to cash when the
regime index (Nifty 50) closes below its 200-day average. Trades happen at
the next session's open.

Idea credit: cross-sectional momentum (Jegadeesh & Titman), absolute
momentum filter (Antonacci), similar in spirit to NSE's momentum indices;
tradermonty theme-detector / sector rotation and exposure-coach.
Parameters are textbook values fixed before testing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

NAME = "momentum_rotation"
VERSION = "1.0.0"


@dataclass(frozen=True)
class RotationParams:
    top_n: int = 5
    hold_rank: int = 10
    min_price: float = 20.0
    regime_index: str = "NIFTY50"
    regime_sma: int = 200
    min_bars: int = 253


PARAMS = RotationParams()


def momentum_score(x: pd.DataFrame) -> pd.Series:
    """Per-row score from causal indicators; NaN when not eligible."""
    vol = x["vol252"].where(x["vol252"] > 0)
    s = 0.5 * x["ret126"] / vol + 0.5 * x["ret252"] / vol
    eligible = (x["close"] > x["sma200"]) & (x["close"] >= PARAMS.min_price)
    return s.where(eligible)


def regime_ok(index_x: pd.DataFrame | None, p: RotationParams = PARAMS) -> pd.Series | None:
    if index_x is None:
        return None
    sma = index_x["close"].rolling(p.regime_sma, min_periods=p.regime_sma).mean()
    return (index_x["close"] > sma)


def rank_universe(scores: dict[str, float]) -> list[tuple[str, float]]:
    """Highest score first; NaN (ineligible) dropped."""
    return sorted(((k, v) for k, v in scores.items() if v is not None and not np.isnan(v)), key=lambda kv: -kv[1])


def describe() -> dict:
    return {"name": NAME, "version": VERSION, "kind": "rotation", "params": asdict(PARAMS),
            "summary": "Monthly: hold the 5 strongest risk-adjusted-momentum stocks above their 200-day average; "
                       "cash when Nifty 50 is below its 200-day average.",
            "exits": "monthly rebalance: sold when rank falls below hold_rank, below SMA200, or regime turns off"}
