import numpy as np
import pandas as pd
import pytest

from india_trading.simulation.timemachine import build_pool, format_result, simulate
from tests.integration.test_backtest_and_workflow import synthetic


def test_probabilities_sum_to_one_and_are_reproducible(big_settings):
    df = synthetic(300)
    close = float(df["close"].iloc[-1])
    a = simulate(df, "SYN", close, close * 0.95, close * 1.10, big_settings, qty=10, paths=2000)
    b = simulate(df, "SYN", close, close * 0.95, close * 1.10, big_settings, qty=10, paths=2000)
    assert a == b
    assert a.p_target + a.p_stop + a.p_gap_stop + a.p_time == pytest.approx(1.0, abs=1e-3)
    assert "VERDICT" in format_result(a)


def test_closer_target_is_hit_more_often(big_settings):
    df = synthetic(300)
    c = float(df["close"].iloc[-1])
    near = simulate(df, "SYN", c, c * 0.95, c * 1.02, big_settings, paths=3000)
    far = simulate(df, "SYN", c, c * 0.95, c * 1.20, big_settings, paths=3000)
    assert near.p_target > far.p_target


def test_charges_are_deducted(settings):
    """At ₹200-type sizes charges dominate: average net is below average gross."""
    df = synthetic(300)
    c = float(df["close"].iloc[-1])
    r = simulate(df, "SYN", c, c * 0.95, c * 1.10, settings, qty=1, paths=2000)
    gross_avg = r.avg_r * (c - c * 0.95)
    assert r.avg_net_inr < gross_avg


def test_pool_uses_only_given_rows_and_needs_history(big_settings):
    df = synthetic(300)
    assert len(build_pool(df, lookback=100)) == 100
    with pytest.raises(ValueError):
        simulate(df.head(30), "SYN", 100, 95, 110, big_settings)
    with pytest.raises(ValueError):
        simulate(df, "SYN", 100, 105, 110, big_settings)   # stop above entry


def test_flat_market_never_hits_far_levels(big_settings):
    n = 200
    flat = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=n), "open": 100.0, "high": 100.5,
                         "low": 99.5, "close": 100.0, "volume": 1000})
    r = simulate(flat, "FLAT", 100, 90, 120, big_settings, paths=500)
    assert r.p_time == 1.0 and r.p_target == 0 and r.p_stop == 0
    assert np.isclose(r.avg_r, 0.0)
