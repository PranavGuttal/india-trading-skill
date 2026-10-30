from datetime import datetime

import pytest

from india_trading.brokers.base import BrokerTimeout
from india_trading.brokers.paper_broker import PaperBroker
from india_trading.execution.executor import Approval, ExecutionAgent
from india_trading.journal.store import Journal
from india_trading.models import OrderIntent, OrderStatus, Side
from india_trading.risk.manager import RiskManager
from tests.conftest import make_proposal, make_quote


def broker(tmp_path, s, price=100.0, fill="full"):
    holder = {"price": price}
    b = PaperBroker(tmp_path / "paper.db", s.max_experimental_allocation_inr, s.charges,
                    price_provider=lambda sym: make_quote(sym, holder["price"]), slippage_bps=10, fill_model=fill)
    return b, holder


def intent(qty=10, price=100.0, side=Side.BUY, ref="r1"):
    return OrderIntent(symbol="ABC", side=side, qty=qty, limit_price=price, product="delivery",
                       stop=95, target=110, trade_date="2025-09-22", proposal_ref=ref)


def test_fill_cash_and_position_accounting(tmp_path, big_settings):
    b, _ = broker(tmp_path, big_settings)
    o = b.place_order(intent())
    assert o.status == OrderStatus.FILLED and o.mode == "paper"
    assert "NOT a real Groww execution" in o.message
    pos = b.get_positions()
    assert pos[0].qty == 10
    assert b.cash() < 20000 - 10 * 100   # charges deducted


def test_round_trip_pnl_includes_all_charges(tmp_path, big_settings):
    b, px = broker(tmp_path, big_settings)
    b.place_order(intent())
    px["price"] = 110.0
    b.place_order(intent(side=Side.SELL, price=109.0, ref="exit"))
    t = b.closed_trades()[0]
    assert t["exit"] == 110.0 * (1 - 0.001) or t["exit"] >= 109.0
    assert t["pnl_net"] < 10 * (t["exit"] - t["entry"])
    assert b.get_positions() == []
    assert b.cash() == pytest.approx(20000 + t["pnl_net"], abs=0.02)


def test_idempotent_duplicate_submission(tmp_path, big_settings):
    b, _ = broker(tmp_path, big_settings)
    i = intent()
    o1 = b.place_order(i)
    o2 = b.place_order(i)
    assert o1.intent_id == o2.intent_id
    assert b.get_positions()[0].qty == 10   # not 20


def test_restart_recovery_keeps_state(tmp_path, big_settings):
    b, _ = broker(tmp_path, big_settings)
    i = intent()
    b.place_order(i)
    cash = b.cash()
    b2, _ = broker(tmp_path, big_settings)          # "restart"
    assert b2.cash() == cash
    assert b2.get_order_status(i.intent_id).status == OrderStatus.FILLED
    b2.place_order(i)                               # replayed request after restart
    assert b2.get_positions()[0].qty == 10


def test_rejected_and_partial_and_resting(tmp_path, big_settings):
    b, _ = broker(tmp_path, big_settings, fill="reject")
    assert b.place_order(intent()).status == OrderStatus.REJECTED
    b, _ = broker(tmp_path / "p2", big_settings, fill="partial")
    o = b.place_order(intent())
    assert o.status == OrderStatus.PARTIALLY_FILLED and o.filled_qty == 5
    b, px = broker(tmp_path / "p3", big_settings, price=101)
    o = b.place_order(intent(price=100))
    assert o.status == OrderStatus.SUBMITTED   # limit not reached
    assert b.cancel_order(o.intent_id).status == OrderStatus.CANCELLED


def test_insufficient_paper_cash(tmp_path, settings):
    b, _ = broker(tmp_path, settings)            # ₹200 account
    o = b.place_order(intent(qty=5, price=100))  # ₹500
    assert o.status == OrderStatus.REJECTED and "insufficient" in o.message


def test_no_short_selling(tmp_path, big_settings):
    b, _ = broker(tmp_path, big_settings)
    with pytest.raises(ValueError):
        b.place_order(intent(side=Side.SELL))


def test_timeout_is_reconciled_not_retried(tmp_path, big_settings, now):
    b, _ = broker(tmp_path, big_settings)
    j = Journal(tmp_path / "j.db")
    acct = b.get_account_state("2025-09-22")
    d = RiskManager(big_settings).evaluate(make_proposal(), make_quote(), acct, now, "2025-09-22", True)
    assert d.approved
    b.fail_next_submit_with_timeout = True
    ex = ExecutionAgent(big_settings, b, j)
    r = ex.execute(d, Approval(d.intent.intent_id, "yes"))
    assert r.order is not None and "reconciled" in r.message
    # a second attempt finds the existing order and does not submit again
    r2 = ex.execute(d, Approval(d.intent.intent_id, "yes"))
    assert r2.message == "duplicate prevented"
    kinds = [e["kind"] for e in j.events()]
    assert kinds.count("ORDER_SUBMITTED") == 1 and "RECOVERY" in kinds


def test_account_state_reflects_pending_and_trades(tmp_path, big_settings):
    b, _ = broker(tmp_path, big_settings, price=101)
    b.place_order(intent(price=100))   # rests
    a = b.get_account_state("2025-09-22")
    assert a.pending_orders == 1 and a.trades_today == 0
