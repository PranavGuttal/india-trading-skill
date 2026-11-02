from datetime import datetime, time

import pytest

from india_trading.brokers.paper_broker import PaperBroker
from india_trading.journal.store import Journal
from india_trading.market_data.calendar import IST, NSECalendar
from india_trading.models import OrderIntent, Quote, Side
from india_trading.risk.manager import AccountState, KillSwitch, RiskManager
from india_trading.workflows.autopilot import AutoPilot
from tests.conftest import make_proposal, make_quote
from tests.helpers import walk, write


def acct(cash, at_stops=None):
    return AccountState(cash_available=cash, open_positions=0, pending_orders=0, realised_pnl_today=0.0,
                        trades_today=0, equity_at_stops=at_stops)


def test_floor_blocks_a_trade_that_could_breach_it(big_settings, now):
    s = big_settings.model_copy(update={"capital_floor_pct": 90.0})        # floor ₹18,000
    rm = RiskManager(s)
    ok = rm.evaluate(make_proposal(), make_quote(), acct(20_000), now, "2025-09-22", True)
    assert ok.approved, ok.reasons
    near = rm.evaluate(make_proposal(), make_quote(), acct(18_050), now, "2025-09-22", True)
    assert not near.approved and any("capital floor" in r for r in near.reasons)


def test_positions_count_at_their_stops_and_floor_can_be_switched_off(big_settings, now):
    s = big_settings.model_copy(update={"capital_floor_pct": 90.0})
    # plenty of cash, but open positions valued at their stops leave little headroom
    d = RiskManager(s).evaluate(make_proposal(), make_quote(), acct(19_000, at_stops=18_100), now, "2025-09-22", True)
    assert not d.approved and any("capital floor" in r for r in d.reasons)
    off = s.model_copy(update={"capital_floor_pct": 0.0})
    d = RiskManager(off).evaluate(make_proposal(), make_quote(), acct(18_050), now, "2025-09-22", True)
    assert not any("capital floor" in r for r in d.reasons)


def test_paper_broker_reports_equity_at_stops_and_stops_never_lower(tmp_path, big_settings):
    q = Quote(symbol="ABC", price=100.0, timestamp=datetime(2025, 9, 22, 11, 0, tzinfo=IST), source="t")
    b = PaperBroker(tmp_path / "p.db", 20_000, big_settings.charges, price_provider=lambda s: q)
    b.place_order(OrderIntent(symbol="ABC", side=Side.BUY, qty=10, limit_price=101, product="delivery",
                              stop=95.0, target=110.0, trade_date="2025-09-22"))
    a = b.get_account_state("2025-09-22")
    assert a.equity_at_stops == pytest.approx(a.cash_available + 10 * 95.0)
    assert b.update_stop("ABC", 97.0) and b.get_positions()[0].stop == 97.0
    assert not b.update_stop("ABC", 90.0) and b.get_positions()[0].stop == 97.0


def test_autopilot_liquidates_and_engages_kill_switch_below_the_floor(tmp_path, big_settings):
    s = big_settings.model_copy(update={"capital_floor_pct": 90.0, "watchlist": ["ABC"]})
    df = walk(300, seed=2)
    write(df, tmp_path / "data", "ABC")
    d = df["date"].iloc[-1].date()
    now = datetime.combine(d, time(15, 20), tzinfo=IST)
    hold = {"q": Quote(symbol="ABC", price=1000.0, timestamp=now, source="t")}
    b = PaperBroker(tmp_path / "p.db", 20_000, s.charges, price_provider=lambda sym: hold["q"], clock=lambda: now)
    b.place_order(OrderIntent(symbol="ABC", side=Side.BUY, qty=10, limit_price=1010, product="delivery",
                              stop=900.0, target=1200.0, trade_date=str(d)))
    pilot = AutoPilot(s, b, Journal(tmp_path / "j.db"), NSECalendar(), tmp_path / "data")
    crash = Quote(symbol="ABC", price=700.0, timestamp=now, source="t")          # equity ≈ 10,000 + 7,000 < 18,000
    rep = pilot.tick(now, {"ABC": crash})
    assert rep.exits and "capital floor" in rep.exits[0]
    assert b.get_positions() == []
    assert KillSwitch(s.state_path("KILL_SWITCH")).engaged
    again = pilot.tick(now, {"ABC": crash})
    assert not again.entries                                                       # stays halted
