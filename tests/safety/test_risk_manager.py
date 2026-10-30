from datetime import timedelta

import pytest

from india_trading.risk.manager import AccountState, KillSwitch, RiskManager
from tests.conftest import make_proposal, make_quote


def acct(**kw):
    base = dict(cash_available=20000, open_positions=0, pending_orders=0, realised_pnl_today=0.0, trades_today=0)
    base.update(kw)
    return AccountState(**base)


def ev(rm, now, prop=None, quote=None, account="default", session=True):
    return rm.evaluate(prop or make_proposal(), quote if quote is not None else make_quote(),
                       acct() if account == "default" else account, now=now, trade_date="2025-09-22",
                       session_open=session)


def test_happy_path_with_practice_budget(big_settings, now):
    d = ev(RiskManager(big_settings), now)
    assert d.approved, d.reasons
    assert d.intent and d.intent.qty == d.qty > 0
    assert d.planned_risk_inr <= big_settings.max_risk_per_trade_inr
    assert d.intent.value + d.est_buy_costs <= big_settings.max_experimental_allocation_inr


def test_default_200_budget_blocks_because_charges_exceed_risk(settings, now):
    d = ev(RiskManager(settings), now, prop=make_proposal(entry=50, stop=48, target=54), quote=make_quote(price=50))
    assert not d.approved
    assert any("charges" in r for r in d.reasons)


def test_order_never_exceeds_budget_or_order_cap(settings, now):
    s = settings.model_copy(update={"max_risk_per_trade_inr": 100, "daily_loss_limit_inr": 150, "min_reward_to_cost": 0.1})
    d = ev(RiskManager(s), now, prop=make_proposal(entry=30, stop=20, target=60), quote=make_quote(price=30))
    if d.approved:
        assert d.intent.value + d.est_buy_costs <= s.max_experimental_allocation_inr
        assert d.intent.value <= s.max_single_order_value_inr


@pytest.mark.parametrize("kw,needle", [
    (dict(quote=make_quote(price=100, delayed=True)), "delayed"),
    (dict(quote=make_quote(price=100, source="x")), None),
])
def test_quote_flags(big_settings, now, kw, needle):
    d = ev(RiskManager(big_settings), now, **kw)
    if needle:
        assert not d.approved and any(needle in r for r in d.reasons)


def test_stale_quote_blocks(big_settings, now):
    q = make_quote(ts=now - timedelta(minutes=10))
    d = ev(RiskManager(big_settings), now, quote=q)
    assert not d.approved and any("stale" in r for r in d.reasons)


def test_future_quote_blocks(big_settings, now):
    d = ev(RiskManager(big_settings), now, quote=make_quote(ts=now + timedelta(minutes=5)))
    assert not d.approved and any("future" in r for r in d.reasons)


def test_missing_quote_and_mismatched_symbol(big_settings, now):
    rm = RiskManager(big_settings)
    assert not rm.evaluate(make_proposal(), None, acct(), now, "2025-09-22", True).approved
    assert not ev(rm, now, quote=make_quote(symbol="XYZ")).approved


def test_price_drift_blocks(big_settings, now):
    d = ev(RiskManager(big_settings), now, quote=make_quote(price=104))
    assert not d.approved and any("away from planned entry" in r for r in d.reasons)


def test_penny_stock_floor(big_settings, now):
    d = ev(RiskManager(big_settings), now, prop=make_proposal(entry=10, stop=9, target=13), quote=make_quote(price=10))
    assert not d.approved and any("penny" in r for r in d.reasons)


def test_unverified_account_fails_closed(big_settings, now):
    rm = RiskManager(big_settings)
    assert not ev(rm, now, account=None).approved
    d = ev(rm, now, account=acct(verified=False))
    assert not d.approved and any("could not be verified" in r for r in d.reasons)


def test_insufficient_funds(big_settings, now):
    d = ev(RiskManager(big_settings), now, account=acct(cash_available=50))
    assert not d.approved


def test_limits_positions_trades_daily_loss(big_settings, now):
    rm = RiskManager(big_settings)
    assert not ev(rm, now, account=acct(open_positions=1)).approved
    assert not ev(rm, now, account=acct(pending_orders=1)).approved
    assert not ev(rm, now, account=acct(trades_today=2)).approved
    d = ev(rm, now, account=acct(realised_pnl_today=-600))
    assert not d.approved and any("daily loss limit" in r for r in d.reasons)


def test_already_holding_symbol(big_settings, now):
    d = ev(RiskManager(big_settings.model_copy(update={"max_open_positions": 5})), now,
           account=acct(open_positions=1, open_symbols={"ABC"}))
    assert not d.approved and any("already holding" in r for r in d.reasons)


def test_session_closed_blocks(big_settings, now):
    assert not ev(RiskManager(big_settings), now, session=False).approved


def test_no_trade_and_kill_switch(big_settings, now, tmp_path):
    rm = RiskManager(big_settings)
    assert not ev(rm, now, prop=make_proposal(decision="NO_TRADE")).approved
    k = KillSwitch(tmp_path / "ks")
    k.engage("test")
    d = RiskManager(big_settings, k).evaluate(make_proposal(), make_quote(), acct(), now, "2025-09-22", True)
    assert not d.approved and d.reasons == ["kill switch is engaged"]
    k.release()
    assert RiskManager(big_settings, k).evaluate(make_proposal(), make_quote(), acct(), now, "2025-09-22", True).approved


def test_reward_risk_minimum(big_settings, now):
    d = ev(RiskManager(big_settings), now, prop=make_proposal(entry=100, stop=95, target=103))
    assert not d.approved and any("reward:risk" in r for r in d.reasons)


def test_duplicate_intent_blocked(big_settings, now):
    rm = RiskManager(big_settings)
    first = ev(rm, now)
    d = ev(rm, now, account=acct(pending_intent_ids={first.intent.intent_id}))
    assert not d.approved and any("duplicate" in r for r in d.reasons)
