from datetime import datetime, time

import pandas as pd

from india_trading.analysis.market_gate import market_ok
from india_trading.backtesting.engine import run_backtest
from india_trading.backtesting.portfolio import LabConfig, run_signal_portfolio
from india_trading.brokers.paper_broker import PaperBroker
from india_trading.config import Settings
from india_trading.journal.store import Journal
from india_trading.market_data.calendar import IST, NSECalendar
from india_trading.models import OrderIntent, Quote, Side
from india_trading.risk.manager import AccountState, RiskManager
from india_trading.strategies import get
from india_trading.workflows.autopilot import AutoPilot
from tests.conftest import make_proposal, make_quote
from tests.helpers import walk, write


def acct():
    return AccountState(cash_available=20_000, open_positions=0, pending_orders=0, realised_pnl_today=0.0, trades_today=0)


def test_defaults_are_protective_and_old_booleans_still_load():
    s = Settings()
    assert s.regime_gate == "index" and s.strategy == "trend_template" and s.capital_floor_pct == 90
    assert Settings(regime_gate=True).regime_gate == "index" and Settings(regime_gate=False).regime_gate == "off"


def test_market_ok_open_closed_unknown_and_stale(tmp_path):
    up, down = walk(300, drift=0.002, vol=0.005, seed=1), walk(300, drift=-0.002, vol=0.005, seed=1)
    write(up, tmp_path / "up", "NIFTY50")
    write(down, tmp_path / "down", "NIFTY50")
    last = up["date"].iloc[-1].date()
    assert market_ok(tmp_path / "up", last)[0] is True
    ok, note = market_ok(tmp_path / "down", last)
    assert ok is False and "below its 200-day average" in note
    assert market_ok(tmp_path / "missing", last)[0] is None
    assert market_ok(tmp_path / "up", up["date"].iloc[100].date())[0] is None           # not enough history
    stale = (up["date"].iloc[-1] + pd.Timedelta(days=30)).date()
    assert market_ok(tmp_path / "up", stale)[0] is None                                  # old data fails closed


def test_risk_manager_blocks_unless_the_gate_is_open(big_settings, now):
    s = big_settings.model_copy(update={"regime_gate": "index"})
    rm = RiskManager(s)
    args = (make_proposal(), make_quote(), acct(), now, "2025-09-22", True)
    assert not rm.evaluate(*args).approved                                             # not supplied -> blocked
    closed = rm.evaluate(*args, market=(False, "market gate: Nifty below"))
    assert not closed.approved and "market gate: Nifty below" in closed.reasons
    assert not rm.evaluate(*args, market=(None, "unknown")).approved
    assert rm.evaluate(*args, market=(True, "open")).approved


def test_autopilot_gate_stops_entries_but_not_exits(tmp_path, big_settings):
    s = big_settings.model_copy(update={"regime_gate": "index", "watchlist": ["ABC"],
                                        "indices_dir": str(tmp_path / "idx")})
    df = walk(300, seed=2)
    write(df, tmp_path / "data", "ABC")
    write(walk(300, drift=-0.002, vol=0.005, seed=3), tmp_path / "idx", "NIFTY50")
    d = df["date"].iloc[-1].date()
    now = datetime.combine(d, time(15, 20), tzinfo=IST)
    hold = {"q": Quote(symbol="ABC", price=1000.0, timestamp=now, source="t")}
    b = PaperBroker(tmp_path / "p.db", 20_000, s.charges, price_provider=lambda sym: hold["q"], clock=lambda: now)
    b.place_order(OrderIntent(symbol="ABC", side=Side.BUY, qty=2, limit_price=1010, product="delivery",
                              stop=990.0, target=1200.0, trade_date=str(d)))
    pilot = AutoPilot(s, b, Journal(tmp_path / "j.db"), NSECalendar(), tmp_path / "data")
    rep = pilot.tick(now, {"ABC": Quote(symbol="ABC", price=980.0, timestamp=now, source="t")})
    assert rep.exits and "stop" in rep.exits[0]                                         # the exit still ran
    assert not rep.entries and rep.regime == "CLOSED" and any("market gate" in n for n in rep.notes)


def test_backtests_skip_entries_while_the_index_is_falling(big_settings):
    s = big_settings.model_copy(update={"regime_gate": "index"})
    df = walk(600, drift=0.0015, vol=0.016, seed=11)
    falling = walk(600, drift=-0.002, vol=0.004, seed=12)
    free = run_backtest(df, "ABC", s.model_copy(update={"regime_gate": "off"}), get("donchian_trend"), "t")
    gated = run_backtest(df, "ABC", s, get("donchian_trend"), "t", regime_index=falling)
    assert free.trades and not gated.trades
    lab = run_signal_portfolio({"ABC": df}, get("donchian_trend"), LabConfig(capital=100_000), regime_index=falling)
    assert lab.trades == [] and lab.name == "donchian_trend+gate"
