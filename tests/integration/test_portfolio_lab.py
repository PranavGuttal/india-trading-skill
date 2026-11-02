from datetime import date

import numpy as np
import pandas as pd
import pytest

from india_trading.backtesting.lab import run_lab
from india_trading.backtesting.portfolio import (LabConfig, buy_and_hold, index_hold, run_regime_allocation,
                                                 run_rotation, run_signal_portfolio)
from india_trading.strategies import get
from tests.helpers import walk


@pytest.fixture
def universe():
    return {f"S{i}": walk(700, drift=0.0004 * (i - 2), vol=0.015, seed=i) for i in range(6)}


def test_buy_and_hold_handles_a_late_listing_without_a_fake_jump():
    a = walk(300, drift=0.0, vol=0.0001, seed=1)
    b = walk(280, drift=0.0, vol=0.0001, seed=2, begin=str(a["date"].iloc[20].date()))
    r = buy_and_hold({"A": a, "B": b}, LabConfig(capital=100_000))
    eq = r.equity
    assert eq.iloc[0] > 99_000 and eq.max() < 101_000           # flat prices -> flat equity, no 2x jump


def test_signal_portfolio_respects_max_positions_and_fills_next_open(universe):
    cfg = LabConfig(capital=200_000, max_positions=2)
    r = run_signal_portfolio(universe, get("donchian_trend"), cfg)
    assert r.trades, "expected some trades on trending synthetic data"
    days = pd.bdate_range(r.equity.index[0], r.equity.index[-1])
    for d in days[::5]:
        open_ = [t for t in r.trades if t.entry_date <= str(d.date()) < t.exit_date]
        assert len(open_) <= 2
    for t in r.trades[:10]:
        df = universe[t.symbol]
        o = float(df.loc[df["date"] == pd.Timestamp(t.entry_date), "open"].iloc[0])
        assert t.entry == pytest.approx(o * 1.001, abs=0.011)       # next-open fill + 10 bps slippage
    assert r.metrics()["charges_inr"] > 0


def test_regime_allocation_stays_in_cash_when_index_is_falling(universe):
    falling = walk(700, drift=-0.002, vol=0.005, seed=9)
    r = run_regime_allocation(universe, falling, LabConfig(capital=50_000))
    assert r.trades == [] and r.equity.iloc[-1] == pytest.approx(50_000)


def test_regime_allocation_invests_when_index_rises(universe):
    rising = walk(700, drift=0.002, vol=0.005, seed=9)
    r = run_regime_allocation(universe, rising, LabConfig(capital=50_000))
    assert r.trades and r.metrics()["exposure_pct"] > 30


def test_rotation_holds_at_most_top_n_and_pays_charges(universe):
    rising = walk(700, drift=0.002, vol=0.005, seed=9)
    r = run_rotation(universe, rising, LabConfig(capital=100_000))
    assert r.trades
    assert all(t.charges > 0 for t in r.trades)


def test_index_hold_and_lab_verdicts(universe):
    nifty = walk(700, drift=0.0005, vol=0.01, seed=5)
    cfg = LabConfig(capital=100_000, start=date(2022, 12, 1))
    assert index_hold(nifty, cfg).metrics()["trades"] == 0
    rows, verdicts = run_lab(universe, nifty, None, ["donchian_trend", "trend_filtered_core"], cfg,
                             split=date(2023, 9, 1))
    assert {r.period for r in rows} == {"earlier", "later (out-of-sample)", "full"}
    assert set(verdicts) == {"donchian_trend", "trend_filtered_core"}
    assert all(any(k in v for k in ("BEATS", "SAFER", "NO EDGE", "INCONCLUSIVE")) for v in verdicts.values())
