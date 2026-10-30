import pytest

from india_trading.brokers.base import UnsupportedOperation
from india_trading.brokers.groww_adapter import GrowwAdapter
from india_trading.config import LIVE_ACK_PHRASE, ConfigError, Settings, load_settings
from india_trading.execution.executor import Approval, ExecutionAgent, ExecutionRefused
from india_trading.journal.store import Journal
from india_trading.risk.manager import AccountState, RiskManager
from tests.conftest import make_proposal, make_quote


def test_defaults_are_safe():
    s = Settings()
    assert s.trading_mode == "paper"
    assert s.live_trading_enabled is False
    assert s.require_human_approval is True
    assert s.max_experimental_allocation_inr == 200
    assert s.max_single_order_value_inr == 200
    assert s.max_open_positions == 1
    assert not (s.allow_short_selling or s.allow_derivatives or s.allow_leverage)
    assert s.live_requested is False


def test_load_settings_without_file_is_safe(tmp_path):
    s = load_settings(tmp_path / "missing.yaml", env={})
    assert s.trading_mode == "paper" and not s.live_requested


@pytest.mark.parametrize("env", [
    {"ALLOW_SHORT_SELLING": "true"}, {"ALLOW_DERIVATIVES": "1"}, {"ALLOW_LEVERAGE": "yes"},
    {"MAX_SINGLE_ORDER_VALUE_INR": "500"},
    {"TRADING_MODE": "live", "REQUIRE_HUMAN_APPROVAL": "false"},
    {"LIVE_TRADING_ENABLED": "maybe"},
])
def test_unsafe_config_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(None, env=env)


def test_live_needs_all_three_switches():
    assert not Settings(trading_mode="live").live_requested
    assert not Settings(trading_mode="live", live_trading_enabled=True).live_requested
    assert Settings(trading_mode="live", live_trading_enabled=True, live_ack=LIVE_ACK_PHRASE).live_requested


def test_groww_adapter_refuses_everything():
    g = GrowwAdapter()
    for call in (lambda: g.get_quote("X"), lambda: g.get_positions(), lambda: g.place_order(None),
                 lambda: g.cancel_order("x"), lambda: g.get_account_state("2025-01-01"),
                 lambda: g.get_order_status("x"), lambda: g.get_historical_bars("X", 5),
                 lambda: g.get_instrument_details("X")):
        with pytest.raises(UnsupportedOperation):
            call()


def _approved_decision(s, now):
    rm = RiskManager(s)
    acct = AccountState(cash_available=20000, open_positions=0, pending_orders=0, realised_pnl_today=0, trades_today=0)
    d = rm.evaluate(make_proposal(), make_quote(), acct, now, "2025-09-22", True)
    assert d.approved
    return d


def test_live_adapter_refused_by_default(big_settings, now, tmp_path):
    d = _approved_decision(big_settings, now)
    ex = ExecutionAgent(big_settings, GrowwAdapter(), Journal(tmp_path / "j.db"))
    with pytest.raises(ExecutionRefused, match="disabled"):
        ex.execute(d, Approval(d.intent.intent_id, "yes"))


def test_live_needs_per_order_approval_even_when_enabled(big_settings, now, tmp_path):
    s = big_settings.model_copy(update={"trading_mode": "live", "live_trading_enabled": True, "live_ack": LIVE_ACK_PHRASE})
    d = _approved_decision(s, now)
    ex = ExecutionAgent(s, GrowwAdapter(), Journal(tmp_path / "j.db"))
    with pytest.raises(ExecutionRefused):
        ex.execute(d, None)
    with pytest.raises(ExecutionRefused):
        ex.execute(d, Approval("some-other-intent", "yes"))
    with pytest.raises(ExecutionRefused):
        ex.execute(d, Approval(d.intent.intent_id, "ok sure"))
    with pytest.raises(ExecutionRefused):
        ex.execute(d, Approval(d.intent.intent_id, "yes to all"))
    # even with a valid approval, the unverified Groww adapter refuses the call
    with pytest.raises(UnsupportedOperation):
        ex.execute(d, Approval(d.intent.intent_id, "yes"))


def test_unapproved_risk_decision_never_executes(big_settings, now, tmp_path):
    from india_trading.brokers.paper_broker import PaperBroker
    from india_trading.models import RiskDecision
    b = PaperBroker(tmp_path / "p.db", 20000, big_settings.charges, price_provider=lambda s: make_quote())
    ex = ExecutionAgent(big_settings, b, Journal(tmp_path / "j.db"))
    with pytest.raises(ExecutionRefused):
        ex.execute(RiskDecision(approved=False, reasons=["x"]))
