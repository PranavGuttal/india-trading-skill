from datetime import datetime, time

import numpy as np
import pandas as pd
import pytest

from india_trading.backtesting.engine import MIN_TRADES_FOR_EVIDENCE, format_report, run_backtest
from india_trading.brokers.paper_broker import PaperBroker
from india_trading.journal.store import Journal, redact
from india_trading.market_data.calendar import IST, NSECalendar
from india_trading.models import Quote, TradeProposal
from india_trading.strategies import ma_trend
from india_trading.workflows.supervisor import Step, Supervisor
from tests.conftest import trend_df


def synthetic(n=400, seed=11):
    rng = np.random.default_rng(seed)
    r = 0.0005 + 0.015 * rng.standard_normal(n)
    close = 150 * np.exp(np.cumsum(r))
    open_ = np.concatenate([[150], close[:-1]])
    df = pd.DataFrame({"date": pd.bdate_range("2023-01-02", periods=n), "open": open_,
                       "high": np.maximum(open_, close) * 1.006, "low": np.minimum(open_, close) * 0.994,
                       "close": close, "volume": (1e6 * np.exp(0.3 * rng.standard_normal(n))).astype(int)})
    return df


def test_backtest_is_reproducible_and_reports(big_settings):
    df = synthetic()
    a = run_backtest(df, "SYN", big_settings, ma_trend.evaluate, "synthetic")
    b = run_backtest(df, "SYN", big_settings, ma_trend.evaluate, "synthetic")
    assert a.metrics() == b.metrics()
    rep = format_report(a)
    for key in ("Net P&L", "win rate", "max DD", "Baseline", "VERDICT", "Train", "Test"):
        assert key in rep
    for t in a.trades:
        assert t.charges > 0 and t.pnl_net == pytest.approx(t.pnl_gross - t.charges, abs=0.02)


def test_backtest_has_no_lookahead(big_settings):
    """Changing bars AFTER a trade's entry decision must not change that decision."""
    df = synthetic()
    base = run_backtest(df, "SYN", big_settings, ma_trend.evaluate, "s")
    if not base.trades:
        pytest.skip("no trades on this synthetic path")
    first = base.trades[0]
    cut = df.index[df["date"] == pd.Timestamp(first.entry_date)][0]
    tampered = df.copy()
    tampered.loc[cut + 1:, ["open", "high", "low", "close"]] *= 0.5   # crash after entry
    alt = run_backtest(tampered, "SYN", big_settings, ma_trend.evaluate, "s")
    assert alt.trades[0].entry_date == first.entry_date
    assert alt.trades[0].entry == first.entry


def test_tiny_budget_backtest_is_inconclusive(settings):
    res = run_backtest(synthetic(), "SYN", settings, ma_trend.evaluate, "s")
    assert len(res.trades) < MIN_TRADES_FOR_EVIDENCE
    assert res.verdict().startswith("INCONCLUSIVE")


def _write(df, tmp_path, sym="ABC"):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    df.to_csv(d / f"{sym}.csv", index=False)
    return d / f"{sym}.csv"


def _find_trade_cut(df):
    for t in range(len(df) - 1, 60, -1):
        if ma_trend.evaluate(df.iloc[: t + 1], "ABC", "s").decision == "TRADE":
            return t
    return None


def test_end_to_end_paper_workflow(tmp_path, big_settings):
    df = synthetic(seed=4)
    t = _find_trade_cut(df)
    if t is None:
        pytest.skip("no signal on this path")
    df = df.iloc[: t + 1]
    path = _write(df, tmp_path)
    close = float(df["close"].iloc[-1])
    now = datetime.combine(df["date"].iloc[-1].date(), time(11, 0), tzinfo=IST)
    quote = Quote(symbol="ABC", price=close, timestamp=now, source="test")
    journal = Journal(tmp_path / "j.db")
    broker = PaperBroker(tmp_path / "p.db", 20000, big_settings.charges, price_provider=lambda s: quote)
    sup = Supervisor(big_settings, broker, journal, NSECalendar())
    # decline -> no order
    st = sup.run_once("ABC", path, quote, now, approve=lambda ticket, iid: None)
    assert st.step == Step.HALTED and "not approved" in st.halted_reason and broker.get_positions() == []
    # approve -> paper fill
    st = sup.run_once("ABC", path, quote, now, approve=lambda ticket, iid: "yes")
    assert st.step == Step.DONE and st.execution_status == "FILLED"
    assert broker.get_positions()[0].symbol == "ABC"
    kinds = [e["kind"] for e in journal.events()]
    for k in ("SIGNAL", "RISK_APPROVED", "TICKET", "APPROVED", "ORDER_SUBMITTED", "FILL", "DECLINED"):
        assert k in kinds
    # running again the same day is blocked (position open / duplicate)
    st = sup.run_once("ABC", path, quote, now, approve=lambda ticket, iid: "yes")
    assert st.step == Step.HALTED
    out = tmp_path / "export.csv"
    assert journal.export_csv(out) == len(journal.events(limit=10_000)) and out.exists()


def test_workflow_halts_on_bad_data(tmp_path, big_settings):
    df = trend_df(80)
    df.loc[10, "high"] = 1.0
    path = _write(df, tmp_path)
    sup = Supervisor(big_settings, PaperBroker(tmp_path / "p.db", 20000, big_settings.charges), Journal(tmp_path / "j.db"), NSECalendar())
    st = sup.run_once("ABC", path, None, datetime(2024, 5, 1, 11, tzinfo=IST))
    assert st.step == Step.HALTED and "invalid" in st.halted_reason


def test_journal_redacts_secrets(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.record("ERROR", "paper", "x", payload={"access_token": "abc", "nested": {"api_key": "k", "price": 1}})
    p = j.events()[0]["payload"]
    assert "abc" not in p and "\"k\"" not in p and "REDACTED" in p and "\"price\": 1" in p
    assert redact({"totp_secret": "s"}) == {"totp_secret": "[REDACTED]"}


def test_journal_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        Journal(tmp_path / "j.db").record("BUY_NOW", "paper")
