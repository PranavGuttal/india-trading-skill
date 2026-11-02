import numpy as np
import pandas as pd
import pytest

from india_trading.backtesting.engine import run_backtest
from india_trading.indicators.core import add_indicators
from india_trading.strategies import ALL_NAMES, SIGNAL_STRATEGIES, get
from india_trading.strategies.base import ExitPolicy, close_rule_exit, effective_stop
from tests.helpers import walk


def test_registry_and_unknown_name():
    assert set(SIGNAL_STRATEGIES) == {"ma_trend_pullback", "donchian_trend", "trend_template", "rsi2_reversion"}
    assert "momentum_rotation" in ALL_NAMES
    assert get(None).name == "ma_trend_pullback"
    with pytest.raises(KeyError):
        get("does_not_exist")


@pytest.mark.parametrize("name", list(SIGNAL_STRATEGIES))
def test_signals_are_causal_and_match_evaluate(name):
    st = SIGNAL_STRATEGIES[name]
    df = walk(520, drift=0.0012, vol=0.015, seed=7)
    x = add_indicators(df)
    full = st.signals(x)
    for t in range(st.min_bars, len(df), 37):
        part = st.signals(add_indicators(df.iloc[: t + 1]))          # recomputed WITHOUT the future
        assert bool(part["signal"].iloc[-1]) == bool(full["signal"].iloc[t])
        p = st.evaluate(df.iloc[: t + 1], "ABC", "test", indicators=x.iloc[: t + 1])
        assert (p.decision == "TRADE") == bool(full["signal"].iloc[t])
        if p.decision == "TRADE":
            assert p.stop < p.entry < p.target
            assert p.stop == pytest.approx(float(full["stop"].iloc[t]), abs=0.011)
        else:
            assert p.reasons


def test_donchian_fires_on_a_new_high_in_an_uptrend():
    df = walk(400, drift=0.002, vol=0.008, seed=3)
    df.loc[df.index[-1], ["high", "close"]] = df["high"].iloc[-60:].max() * 1.03
    p = get("donchian_trend").evaluate(df, "ABC", "test")
    assert p.decision == "TRADE"
    assert any("planning" in r for r in p.reasons)        # no take-profit: target is for planning only


def test_rsi2_fires_on_a_sharp_dip_above_the_200_day_average():
    df = walk(300, drift=0.002, vol=0.006, seed=4)
    for k, f in zip(range(3, 0, -1), (0.98, 0.97, 0.97)):
        i = df.index[-k]
        df.loc[i, "close"] = df.loc[i - 1, "close"] * f
        df.loc[i, "low"] = min(df.loc[i, "low"], df.loc[i, "close"])
        df.loc[i, "high"] = max(df.loc[i, "high"], df.loc[i, "close"], df.loc[i, "open"])
    p = get("rsi2_reversion").evaluate(df, "ABC", "test")
    assert p.decision == "TRADE", p.reasons


def test_trailing_stop_only_ratchets_up_and_close_rules():
    pol = ExitPolicy(take_profit=False, trail_atr=3.0, close_below="sma50", max_hold_days=50)
    closes = pd.Series([100, 110, 120, 105])
    assert effective_stop(pol, 90, closes, 5.0) == 105.0           # 120 - 3*5
    assert effective_stop(pol, 110, closes, 5.0) == 110.0          # never lowered
    assert effective_stop(ExitPolicy(), 90, closes, 5.0) == 90.0   # no trail configured
    assert close_rule_exit(pol, pd.Series({"close": 95.0, "sma50": 100.0})) == "close < sma50"
    assert close_rule_exit(pol, pd.Series({"close": 105.0, "sma50": 100.0})) == ""
    assert close_rule_exit(ExitPolicy(close_above="sma5"), pd.Series({"close": 105.0, "sma5": 100.0})) == "close > sma5"


def test_backtest_runs_every_strategy_with_its_own_exits(big_settings):
    df = walk(600, drift=0.0015, vol=0.016, seed=11)
    for name, st in SIGNAL_STRATEGIES.items():
        res = run_backtest(df, "ABC", big_settings, st, "test")
        assert res.strategy == name
        for t in res.trades:
            assert t.entry_date > "" and t.exit_date >= t.entry_date
            if not st.exit.take_profit:
                assert t.reason != "target"
            assert t.reason in {"gap below stop", "stop", "trailing stop", "target", "max hold",
                                "trend exit (close < SMA50)", "close < ll20", "close > sma5", "close < sma50"}
