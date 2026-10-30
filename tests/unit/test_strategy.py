import pandas as pd
import pytest

from india_trading.models import TradeProposal
from india_trading.strategies import ma_trend
from tests.conftest import trend_df


def test_insufficient_bars_is_no_trade():
    p = ma_trend.evaluate(trend_df(30), "ABC", "test")
    assert p.decision == "NO_TRADE" and "need" in p.reasons[0]


def test_downtrend_is_no_trade():
    df = trend_df(120, start=200, step=-0.5)
    p = ma_trend.evaluate(df, "ABC", "test")
    assert p.decision == "NO_TRADE"
    assert any("no uptrend" in r for r in p.reasons)


def test_low_relative_volume_blocks():
    df = trend_df(120)
    df.loc[df.index[-1], "volume"] = 10
    p = ma_trend.evaluate(df, "ABC", "test")
    assert p.decision == "NO_TRADE" and any("rel. volume" in r for r in p.reasons)


def test_trade_levels_are_consistent_when_signal():
    # gentle uptrend with a pullback to SMA20 on the last bars
    df = trend_df(120, step=0.3, seed=5)
    p = ma_trend.evaluate(df, "ABC", "test")
    if p.decision == "TRADE":
        assert p.stop < p.entry < p.target
        assert p.target - p.entry == pytest.approx(ma_trend.PARAMS.target_r * (p.entry - p.stop), abs=0.02)
        assert p.max_hold_days == ma_trend.PARAMS.max_hold_days
    else:
        assert p.reasons  # abstention always explains itself


def test_proposal_model_rejects_inverted_levels():
    from datetime import datetime
    from india_trading.market_data.calendar import IST
    with pytest.raises(ValueError):
        TradeProposal(decision="TRADE", symbol="X", strategy="s", strategy_version="1",
                      as_of=datetime(2025, 1, 1, tzinfo=IST), data_source="t", entry=100, stop=105, target=110)
