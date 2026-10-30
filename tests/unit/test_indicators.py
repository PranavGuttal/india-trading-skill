import math

import numpy as np
import pandas as pd
import pytest

from india_trading.indicators.core import (add_indicators, atr, ema, macd, relative_volume, rsi, sma,
                                           support_resistance, true_range, vwap)
from tests.conftest import trend_df


def test_sma_known_values():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = sma(s, 3)
    assert out.isna().tolist()[:2] == [True, True]
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ema(s, 3)
    # seed = mean(1,2,3)=2; alpha=0.5 -> 0.5*4+0.5*2=3 -> 0.5*5+0.5*3=4
    assert math.isnan(out.iloc[1])
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_rsi_extremes_and_known_value():
    up = pd.Series(np.arange(1, 30, dtype=float))
    assert rsi(up, 14).iloc[-1] == 100.0
    down = pd.Series(np.arange(30, 1, -1, dtype=float))
    assert rsi(down, 14).iloc[-1] == pytest.approx(0.0)
    flat = pd.Series([10.0] * 20)
    assert rsi(flat, 14).iloc[-1] == 50.0
    # alternating +1/-1 -> equal average gain/loss -> 50
    alt = pd.Series(np.cumsum([0] + [1, -1] * 15, dtype=float) + 100)
    assert rsi(alt, 14).iloc[-1] == pytest.approx(50.0, abs=4)


def test_true_range_and_atr():
    df = pd.DataFrame({"high": [10, 12, 11], "low": [8, 9, 7], "close": [9, 11, 8]}, dtype=float)
    tr = true_range(df)
    assert tr.tolist() == [2.0, 3.0, 4.0]  # 12-9 ; max(11-7, |11-11|, |7-11|)=4
    a = atr(df, 2)
    assert math.isnan(a.iloc[0])
    assert a.iloc[1] == pytest.approx(2.5)
    assert a.iloc[2] == pytest.approx((2.5 * 1 + 4) / 2)


def test_macd_columns_and_sign_in_uptrend():
    df = trend_df(100)
    m = macd(df["close"])
    assert set(m.columns) == {"macd", "signal", "hist"}
    assert m["macd"].iloc[-1] > 0


def test_relative_volume_excludes_today():
    v = pd.Series([100.0] * 20 + [300.0])
    rv = relative_volume(v, 20)
    assert rv.iloc[-1] == pytest.approx(3.0)


def test_vwap_simple():
    bars = pd.DataFrame({"high": [11, 12], "low": [9, 10], "close": [10, 11], "volume": [100, 300]}, dtype=float)
    out = vwap(bars)
    assert out.iloc[0] == pytest.approx(10.0)
    assert out.iloc[1] == pytest.approx((10 * 100 + 11 * 300) / 400)


def test_support_resistance_uses_prior_bars_only():
    df = trend_df(30)
    sr = support_resistance(df, 5)
    assert sr["resistance"].iloc[10] == df["high"].iloc[5:10].max()


def test_indicators_are_causal():
    """No look-ahead: values at row t are identical whether or not later rows exist."""
    df = trend_df(150, seed=3)
    full = add_indicators(df)
    for t in (60, 90, 149):
        part = add_indicators(df.iloc[: t + 1])
        cols = ["sma20", "sma50", "rsi14", "atr14", "relvol20", "support20", "macd", "macd_signal"]
        pd.testing.assert_series_equal(part[cols].iloc[-1], full[cols].iloc[t], check_names=False)
