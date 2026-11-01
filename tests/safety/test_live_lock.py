from datetime import datetime, timedelta

import pytest

from india_trading.config import LIVE_ACK_PHRASE
from india_trading.journal.store import Journal
from india_trading.live.desk import LiveDesk
from india_trading.live.graduation import check
from india_trading.live.guard import decide
from india_trading.live.ledger import LedgerError, LiveLedger
from india_trading.market_data.calendar import IST, NSECalendar
from india_trading.models import OrderIntent, Side

NOW = datetime(2025, 9, 22, 11, 0, tzinfo=IST)
TOOLS = {"read_only": {"mcp__groww__holdings"},
         "order_tools": {"mcp__groww__order": {"symbol": "sym", "side": "txn", "qty": "q", "price": "px",
                                               "side_values": {"BUY": "B", "SELL": "S"}}}}


def live_settings(s):
    return s.model_copy(update={"trading_mode": "live", "live_trading_enabled": True, "live_ack": LIVE_ACK_PHRASE})


def intent(qty=2, px=95.0, side=Side.BUY):
    return OrderIntent(symbol="ABC", side=side, qty=qty, limit_price=px, product="delivery",
                       trade_date="2025-09-22", stop=90, target=105, proposal_ref="t")


def call(qty=2, px=95.0, txn="B", tool="mcp__groww__order"):
    return {"tool_name": tool, "tool_input": {"sym": "ABC", "txn": txn, "q": qty, "px": px}}


# ---------------------------------------------------------------- graduation
def _closed(n, pnl=5.0, days=None):
    return [{"pnl_net": pnl, "trade_date": f"2025-{1 + (i % (days or n)) // 28:02d}-{1 + (i % (days or n)) % 28:02d}"}
            for i in range(n)]


def _events(ids, src="csv:INFY.csv (nse-historical)", quote="manual:groww-mcp"):
    return ([{"kind": "RISK_APPROVED", "intent_id": i, "data_source": src, "payload": f'{{"quote_source": "{quote}"}}'}
             for i in ids] + [{"kind": "APPROVED", "intent_id": i} for i in ids])


def test_graduation_needs_trades_days_profit(settings):
    ids = [f"i{k}" for k in range(30)]
    assert check(settings, _closed(30), ids, _events(ids)).passed
    assert not check(settings, _closed(29), ids, _events(ids)).passed            # too few trades
    assert not check(settings, _closed(30, days=5), ids, _events(ids)).passed    # too few days
    assert not check(settings, _closed(30, pnl=-1), ids, _events(ids)).passed    # losing


def test_graduation_rejects_synthetic_or_replay_entries(settings):
    ids = [f"i{k}" for k in range(30)]
    assert not check(settings, _closed(30), ids, _events(ids, src="csv:SYNTH_TREND.csv (SYNTHETIC)")).passed
    assert not check(settings, _closed(30), ids, _events(ids, quote="replay:last-close (NOT live)")).passed
    no_yes = [e for e in _events(ids) if e["kind"] != "APPROVED"]
    assert not check(settings, _closed(30), ids, no_yes).passed


def test_graduation_floor_cannot_be_lowered():
    from india_trading.config import Settings
    with pytest.raises(Exception):
        Settings(graduation_min_trades=5)
    with pytest.raises(Exception):
        Settings(live_approval_ttl_seconds=3600)


# ---------------------------------------------------------------- ledger
def test_ticket_must_be_approved_then_sent_once(tmp_path):
    led = LiveLedger(tmp_path / "live.db")
    t = led.prepare(intent(), "ENTRY", NOW)
    assert led.consume("ABC", "BUY", 2, 95.0, NOW, 300)[0] is None              # not approved yet
    with pytest.raises(LedgerError):
        led.approve(t["intent_id"], "ok", NOW)                                   # not an explicit yes
    led.approve(t["intent_id"], "yes", NOW)
    assert led.consume("ABC", "BUY", 3, 95.0, NOW, 300)[0] is None              # wrong qty
    assert led.consume("ABC", "BUY", 2, 96.0, NOW, 300)[0] is None              # wrong price
    assert led.consume("ABC", "BUY", 2, None, NOW, 300)[0] is None              # market order
    sent, _ = led.consume("ABC", "BUY", 2, 95.0, NOW, 300)
    assert sent and sent["status"] == "SENT"
    assert led.consume("ABC", "BUY", 2, 95.0, NOW, 300)[0] is None              # never twice


def test_approval_expires(tmp_path):
    led = LiveLedger(tmp_path / "live.db")
    t = led.prepare(intent(), "ENTRY", NOW)
    led.approve(t["intent_id"], "yes", NOW)
    assert led.consume("ABC", "BUY", 2, 95.0, NOW + timedelta(seconds=301), 300)[0] is None
    assert led.get(t["intent_id"])["status"] == "EXPIRED"


def test_fills_build_positions_and_account_fails_closed(tmp_path, settings):
    led = LiveLedger(tmp_path / "live.db")
    t = led.prepare(intent(), "ENTRY", NOW)
    led.approve(t["intent_id"], "yes", NOW)
    led.consume("ABC", "BUY", 2, 95.0, NOW, 300)
    with pytest.raises(LedgerError):
        led.record(t["intent_id"], "FILLED", "G1", 3, 95.0)                     # more than ordered
    led.record(t["intent_id"], "FILLED", "G1", 2, 95.0)
    assert led.positions()["ABC"]["qty"] == 2
    acct = led.account_state(settings, "2025-09-22", broker_cash=None)
    assert not acct.verified and acct.cash_available == 0                        # no Groww cash -> unverified
    acct = led.account_state(settings, "2025-09-22", broker_cash=10_000)
    assert acct.verified and acct.cash_available == pytest.approx(200 - 190)    # capped by the app budget


# ---------------------------------------------------------------- guard hook
def _decision(out):
    return out.get("hookSpecificOutput", {}).get("permissionDecision")


def test_guard_denies_unclassified_and_when_locked(tmp_path, settings):
    led = LiveLedger(tmp_path / "live.db")
    assert _decision(decide(call(tool="mcp__groww__mystery"), live_settings(settings), TOOLS, led, NOW)) == "deny"
    assert _decision(decide(call(), settings, TOOLS, led, NOW)) == "deny"        # live switches off
    assert decide({"tool_name": "mcp__groww__holdings", "tool_input": {}}, settings, TOOLS, led, NOW) == {}
    assert decide({"tool_name": "Bash", "tool_input": {}}, settings, TOOLS, led, NOW) == {}


def test_guard_asks_only_for_the_exact_approved_ticket(tmp_path, settings):
    s = live_settings(settings)
    led = LiveLedger(tmp_path / "live.db")
    assert _decision(decide(call(), s, TOOLS, led, NOW)) == "deny"               # no ticket
    t = led.prepare(intent(), "ENTRY", NOW)
    led.approve(t["intent_id"], "yes", NOW)
    assert _decision(decide(call(qty=5), s, TOOLS, led, NOW)) == "deny"
    assert _decision(decide(call(txn="S"), s, TOOLS, led, NOW)) == "deny"
    assert _decision(decide(call(), s, TOOLS, led, NOW)) == "ask"
    assert _decision(decide(call(), s, TOOLS, led, NOW)) == "deny"               # used up


# ---------------------------------------------------------------- desk
def test_desk_refuses_entry_before_graduation(tmp_path, settings):
    s = live_settings(settings)
    desk = LiveDesk(s, Journal(tmp_path / "j.db"), NSECalendar(), tmp_path)
    r = desk.prepare_entry("ABC", 100.0, "groww-mcp", 10_000, now=NOW)
    assert not r.ok and r.message == "LIVE LOCKED" and any("graduation" in x for x in r.reasons)
    assert desk.ledger.tickets() == []


def test_desk_refuses_everything_with_switches_off(tmp_path, settings):
    desk = LiveDesk(settings, Journal(tmp_path / "j.db"), NSECalendar(), tmp_path)
    assert not desk.prepare_entry("ABC", 100.0, "groww-mcp", 10_000, now=NOW).ok
    assert not desk.prepare_exit("ABC", 100.0, "groww-mcp", "stop", now=NOW).ok
