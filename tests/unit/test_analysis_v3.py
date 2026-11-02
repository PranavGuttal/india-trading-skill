from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from india_trading.analysis import actions, alerts, planner, portfolio, regime, screener, sectors, technical
from india_trading.config import Settings
from india_trading.market_data.calendar import IST
from india_trading.market_data.csv_source import bad_ticks, validate_bars
from india_trading.market_data.yahoo_source import yahoo_symbol
from india_trading.models import Quote
from india_trading.strategies import get
from india_trading.workflows.allocation import AllocationPilot, targets
from india_trading.journal.store import Journal
from tests.helpers import walk


def test_regime_uptrend_vs_downtrend():
    up = regime.compute(walk(400, drift=0.0015, vol=0.006, seed=1))
    assert up.trend_filter_on and up.exposure_pct >= 70 and "trend filter ON" in up.reasons[0]
    down = regime.compute(walk(400, drift=-0.0015, vol=0.006, seed=1))
    assert not down.trend_filter_on and down.exposure_pct <= 40
    assert "heuristic" in regime.format_regime(down)


def test_distribution_day_needs_a_drop_on_higher_volume():
    ix = walk(60, drift=0.0, vol=0.001, seed=2)
    ix.loc[ix.index[-1], "close"] = ix["close"].iloc[-2] * 0.99
    ix.loc[ix.index[-1], "volume"] = ix["volume"].iloc[-2] * 2
    assert regime.distribution_days(ix) == [len(ix) - 1]
    ix.loc[ix.index[-1], "volume"] = 0                       # missing index volume is never counted
    assert regime.distribution_days(ix) == []


def test_sector_rank_puts_relative_strength_first():
    nifty = walk(300, drift=0.0005, seed=3)
    rows = sectors.rank({"STRONG": walk(300, drift=0.003, seed=4), "WEAK": walk(300, drift=-0.002, seed=5)}, nifty)
    assert [r.name for r in rows] == ["STRONG", "WEAK"] and rows[0].rs6m > rows[1].rs6m


def test_screener_rs_and_setups():
    frames = {"UP": walk(400, drift=0.002, vol=0.01, seed=6), "DOWN": walk(400, drift=-0.002, vol=0.01, seed=7)}
    rows = {r.symbol: r for r in screener.screen(frames)}
    assert rows["UP"].rs > rows["DOWN"].rs
    assert rows["UP"].stage.startswith("2") and rows["DOWN"].stage.startswith("4")
    assert "screen" in screener.format_screen(list(rows.values())).lower()


def test_technical_levels_bracket_the_price():
    df = walk(400, drift=0.0003, vol=0.015, seed=8)
    t = technical.analyse(df, "ABC", "test", nifty=walk(400, seed=9))
    assert all(s < t.close for s in t.supports) and all(r > t.close for r in t.resistances)
    assert set(t.strategies) >= {"ma_trend_pullback", "donchian_trend"} and t.rs_nifty


def test_size_includes_charges_and_refuses_tiny_budgets():
    s = Settings()
    z = planner.size(500, 480, risk_inr=300, budget_inr=10_000, s=s)
    assert z.qty > 0 and z.loss_at_stop <= 300
    assert z.loss_at_stop > z.qty * 20                       # charges are part of the loss
    tiny = planner.size(500, 480, risk_inr=10, budget_inr=200, s=s)
    assert tiny.qty == 0 and tiny.notes
    p = planner.plan("ABC", 100, 95, 115, s, get("donchian_trend").exit, risk_inr=500, budget_inr=10_000)
    assert p.targets == {"1R": 105.0, "2R": 110.0, "3R": 115.0} and p.breakeven > 100


def test_portfolio_review_aliases_and_triggers(tmp_path):
    f = tmp_path / "h.csv"
    f.write_text("tradingSymbol,quantity,average_price\nAAA-EQ,100,200\nBBB,1,100\n", encoding="utf-8")
    hs = portfolio.load_holdings(f)
    assert [h.symbol for h in hs] == ["AAA", "BBB"]
    frames = {"AAA": walk(300, drift=-0.003, seed=10), "BBB": walk(300, seed=11)}
    r = portfolio.review(hs, frames, {"AAA": {"sector": "IT"}})
    aaa = next(v for v in r.rows if v.symbol == "AAA")
    assert any(t.startswith("T3") for t in aaa.triggers) and any(t.startswith("T6") for t in aaa.triggers)
    assert "never 'sell automatically'" in portfolio.format_portfolio(r, "test")


def test_alert_rules_validate_and_trigger(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("alerts:\n  - {symbol: AAA, above: 1}\n  - {symbol: AAA, below: 1}\n", encoding="utf-8")
    out = alerts.evaluate(alerts.load_rules(p), {"AAA": walk(300, seed=12)})
    assert [a.kind for a in out] == ["above"]
    p.write_text("alerts:\n  - {symbol: AAA, cross_above: sma7}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        alerts.load_rules(p)
    p.write_text("alerts:\n  - {symbol: AAA, abvoe: 10}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        alerts.load_rules(p)


def test_corporate_action_yield():
    df = walk(300, seed=13)
    last = df["date"].iloc[-1]
    ev = [{"date": str((last - pd.Timedelta(days=30)).date()), "type": "dividend", "amount": 5.0},
          {"date": str((last - pd.Timedelta(days=400)).date()), "type": "dividend", "amount": 8.0}]
    a = actions.summarise("ABC", df, ev)
    assert a.dividends_12m == 5.0 and a.dividends_prev_12m == 8.0
    assert a.yield_12m_pct == pytest.approx(100 * 5 / float(df["close"].iloc[-1]), abs=0.01)
    assert "cut" in actions.format_actions([a])


def test_bad_ticks_flag_spikes_but_not_real_moves():
    df = walk(100, vol=0.002, seed=14)
    spike = df.copy()
    spike.loc[50:51, ["open", "high", "low", "close"]] = spike.loc[50:51, ["open", "high", "low", "close"]] / 10
    assert bad_ticks(spike).sum() == 2 and not validate_bars(spike).ok
    crash = df.copy()
    crash.loc[50:, ["open", "high", "low", "close"]] = crash.loc[50:, ["open", "high", "low", "close"]] * 0.55
    assert bad_ticks(crash).sum() == 0                        # a move that persists is real


def test_yahoo_symbols_for_stocks_and_indices():
    assert yahoo_symbol("infy") == "INFY.NS" and yahoo_symbol("M&M") == "M&M.NS"
    assert yahoo_symbol("NIFTY50") == "^NSEI" and yahoo_symbol("INDIAVIX") == "^INDIAVIX"


def test_allocation_targets_and_paper_rebalance(tmp_path):
    up, down = walk(300, drift=0.002, vol=0.005, seed=15), walk(300, drift=-0.002, vol=0.005, seed=15)
    etf = {"NIFTYBEES": walk(300, start=250, seed=16)}
    assert targets("etf_trend", up, etf, set()).targets == ["NIFTYBEES"]
    assert targets("etf_trend", down, etf, set()).targets == []
    with pytest.raises(KeyError):
        targets("nope", up, etf, set())
    s = Settings(state_dir=str(tmp_path / "state"), max_experimental_allocation_inr=10_000,
                 max_single_order_value_inr=10_000, daily_loss_limit_inr=100)
    pilot = AllocationPilot(s, Journal(tmp_path / "j.db"))
    now = datetime(2025, 9, 30, 15, 20, tzinfo=IST)
    q = {"NIFTYBEES": Quote(symbol="NIFTYBEES", price=250.0, timestamp=now, source="t")}
    out = pilot.rebalance(targets("etf_trend", up, etf, set()), q, now)
    assert pilot.held().get("NIFTYBEES", 0) > 30 and any("BUY" in x for x in out)
    crash = {"NIFTYBEES": Quote(symbol="NIFTYBEES", price=150.0, timestamp=now, source="t")}
    out = pilot.rebalance(targets("etf_trend", up, etf, {"NIFTYBEES"}), crash, now)
    assert any("capital floor" in x for x in out) and pilot.held() == {}
