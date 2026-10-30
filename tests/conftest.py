from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from india_trading.config import Settings
from india_trading.market_data.calendar import IST
from india_trading.models import Quote, TradeProposal


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(state_dir=str(tmp_path / "state"), data_dir=str(tmp_path / "data"))


@pytest.fixture
def big_settings(tmp_path) -> Settings:
    """A practice budget large enough that charges do not dominate."""
    return Settings(state_dir=str(tmp_path / "state"), data_dir=str(tmp_path / "data"),
                    max_experimental_allocation_inr=20000, max_single_order_value_inr=20000,
                    max_risk_per_trade_inr=200, daily_loss_limit_inr=600)


@pytest.fixture
def now() -> datetime:
    return datetime(2025, 9, 22, 11, 0, tzinfo=IST)  # a Monday, in session


def make_quote(symbol="ABC", price=100.0, ts=None, source="test", delayed=False) -> Quote:
    return Quote(symbol=symbol, price=price, timestamp=ts or datetime(2025, 9, 22, 11, 0, tzinfo=IST),
                 source=source, is_delayed=delayed)


def make_proposal(symbol="ABC", entry=100.0, stop=95.0, target=110.0, decision="TRADE") -> TradeProposal:
    return TradeProposal(decision=decision, symbol=symbol, strategy="test", strategy_version="0",
                         as_of=datetime(2025, 9, 22, 10, 59, tzinfo=IST), data_source="test",
                         reasons=["test"], entry=entry if decision == "TRADE" else None,
                         stop=stop if decision == "TRADE" else None, target=target if decision == "TRADE" else None,
                         max_hold_days=10)


def trend_df(n=120, start=100.0, step=0.4, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start + step * np.arange(n) + rng.normal(0, 0.3, n)
    open_ = np.concatenate([[start], close[:-1]])
    high = np.maximum(open_, close) + 0.5
    low = np.minimum(open_, close) - 0.5
    vol = np.full(n, 100_000)
    return pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=n), "open": open_, "high": high,
                         "low": low, "close": close, "volume": vol})
