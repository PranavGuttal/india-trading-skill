from datetime import datetime, time

import pytest

from india_trading.brokers.groww_adapter import GrowwAdapter
from india_trading.brokers.paper_broker import PaperBroker
from india_trading.execution.executor import ExecutionRefused
from india_trading.journal.store import Journal
from india_trading.market_data.calendar import IST, NSECalendar
from india_trading.models import Quote
from india_trading.risk.manager import AccountState, KillSwitch, RiskManager, pnl_history_stats
from india_trading.workflows.autopilot import AUTO_REPLY, AutoPilot, exit_decision
from tests.conftest import make_proposal, make_quote
from tests.integration.test_backtest_and_workflow import _find_trade_cut, synthetic


def acct(**kw):
    base = dict(cash_available=20000, open_positions=0, pending_orders=0, realised_pnl_today=0.0, trades_today=0)
    base.update(kw)
    return AccountState(**base)


def ev(rm, now, account):
    return rm.evaluate(make_proposal(), make_quote(), account, now=now, trade_date="2025-09-22", session_open=True)


def test_history_stats():
    closed = [("2025-09-01", 50.0), ("2025-09-15", -10.0), ("2025-09-18", -5.0), ("2025-09-19", -1.0)]
    h = pnl_history_stats(closed, "2025-09-22")
    assert h["losing_streak"] == 3 and h["last_loss_date"] == "2025-09-19"
    assert h["realised_pnl_week"] == 0 and h["realised_pnl_month"] == 34.0
    assert pnl_history_stats(closed + [("2025-09-22", 3.0)], "2025-09-22")["losing_streak"] == 0


def test_losing_streak_cools_off_then_releases(big_settings, now):
    rm = RiskManager(big_settings)
    hot = ev(rm, now, acct(losing_streak=3, last_loss_date="2025-09-19"))   # 1 business day ago
    assert not hot.approved and any("losses in a row" in r for r in hot.reasons)
    cool = ev(rm, now, acct(losing_streak=3, last_loss_date="2025-09-17"))  # 3 business days ago
    assert cool.approved, cool.reasons


def test_weekly_and_monthly_limits_block(big_settings, now):
    rm = RiskManager(big_settings)
    w = ev(rm, now, acct(realised_pnl_week=-big_settings.weekly_loss_limit))
    assert not w.approved and any("weekly loss limit" in r for r in w.reasons)
    m = ev(rm, now, acct(realised_pnl_month=-big_settings.monthly_loss_limit))
    assert not m.approved and any("monthly loss limit" in r for r in m.reasons)


def test_limits_default_to_multiples_of_daily(settings):
    assert settings.weekly_loss_limit == 2 * settings.daily_loss_limit_inr
    assert settings.monthly_loss_limit == 4 * settings.daily_loss_limit_inr


def test_autopilot_refuses_live_adapter(tmp_path, settings):
    with pytest.raises(ExecutionRefused):
        AutoPilot(settings, GrowwAdapter(), Journal(tmp_path / "j.db"), NSECalendar(), tmp_path)


@pytest.mark.parametrize("bar,expect", [
    ((94, 96, 93, 95), "gap below stop"),
    ((100, 101, 94, 99), "stop"),
    ((100, 111, 99, 105), "target"),
    ((100, 112, 94, 100), "stop"),           # both touched: stop wins (conservative)
    ((100, 101, 99, 98), "trend exit (close < SMA50)"),
])
def test_exit_rules(bar, expect):
    px, why = exit_decision(bar, stop=95, target=110, sma50=99, held_days=1, max_hold_days=10)
    assert why == expect and px is not None


def test_exit_holds_then_max_hold():
    assert exit_decision((100, 101, 99, 100), 95, 110, 90, 3, 10) == (None, "")
    assert exit_decision((100, 101, 99, 100), 95, 110, 90, 10, 10) == (100, "max hold")


def _setup(tmp_path, big_settings):
    df = synthetic(seed=4)
    t = _find_trade_cut(df)
    if t is None:
        pytest.skip("no signal on this path")
    df = df.iloc[: t + 1]
    (tmp_path / "data").mkdir(exist_ok=True)
    df.to_csv(tmp_path / "data" / "ABC.csv", index=False)
    s = big_settings.model_copy(update={"watchlist": ["ABC"]})
    d = df["date"].iloc[-1].date()
    now = datetime.combine(d, time(15, 20), tzinfo=IST)
    broker = PaperBroker(tmp_path / "p.db", 20000, s.charges, clock=lambda: now)
    journal = Journal(tmp_path / "j.db")
    return s, df, d, now, broker, journal


def test_autopilot_enters_with_auto_approval_and_journals_it(tmp_path, big_settings):
    s, df, d, now, broker, journal = _setup(tmp_path, big_settings)
    pilot = AutoPilot(s, broker, journal, NSECalendar(), tmp_path / "data")
    q = Quote(symbol="ABC", price=float(df["close"].iloc[-1]), timestamp=now, source="test")
    rep = pilot.tick(now, {"ABC": q}, as_of=d)
    assert rep.entries and broker.get_positions()[0].symbol == "ABC"
    approved = [e for e in journal.events() if e["kind"] == "APPROVED"]
    assert approved and AUTO_REPLY[:20] in approved[0]["summary"]
    # same tick again: already holding -> no second order
    rep2 = pilot.tick(now, {"ABC": q}, as_of=d)
    assert not rep2.entries and len(broker.get_positions()) == 1


def test_kill_switch_blocks_autopilot_entries(tmp_path, big_settings):
    s, df, d, now, broker, journal = _setup(tmp_path, big_settings)
    KillSwitch(s.state_path("KILL_SWITCH")).engage("test")
    pilot = AutoPilot(s, broker, journal, NSECalendar(), tmp_path / "data")
    q = Quote(symbol="ABC", price=float(df["close"].iloc[-1]), timestamp=now, source="test")
    rep = pilot.tick(now, {"ABC": q}, as_of=d)
    assert not rep.entries and broker.get_positions() == []
    assert any("kill switch" in r for r in rep.blocked.get("ABC", []))


def test_autopilot_at_200_budget_places_nothing(tmp_path, settings):
    s, df, d, now, broker, journal = _setup(tmp_path, settings)
    broker = PaperBroker(tmp_path / "p200.db", 200, s.charges, clock=lambda: now)
    pilot = AutoPilot(s, broker, journal, NSECalendar(), tmp_path / "data")
    q = Quote(symbol="ABC", price=float(df["close"].iloc[-1]), timestamp=now, source="test")
    rep = pilot.tick(now, {"ABC": q}, as_of=d)
    assert not rep.entries and broker.get_positions() == []
