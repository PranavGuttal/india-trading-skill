"""v0.4.1 hardening: guard covers every MCP server, Claude-send needs Claude Code +
guard hook, app-placed orders are recorded but never sendable by Claude, and
graduation checks typed paper prices against real bars."""
import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from india_trading.cli import build_parser
from india_trading.live.graduation import check, verify_entry_prices
from india_trading.live.guard import decide, load_tools
from india_trading.live.ledger import LedgerError, LiveLedger
from india_trading.live.runtime import check as runtime_check
from india_trading.market_data.calendar import IST
from tests.safety.test_live_lock import NOW, TOOLS, _closed, _decision, _events, call, intent, live_settings

TOOLS_X = {**TOOLS, "allow_other": {"mcp__shop__track_order"}}


# ---------------------------------------------------------------- guard: any server
@pytest.mark.parametrize("tool", [
    "mcp__Broker__place_order", "mcp__claude_ai_MyStocks__buy_stock", "mcp__x__modify_order",
    "mcp__x__cancel_order", "mcp__x__create_gtt", "mcp__x__square_off_all", "mcp__x__exit_position",
])
def test_guard_denies_order_like_tools_from_unnamed_connectors(tmp_path, settings, tool):
    led = LiveLedger(tmp_path / "live.db")
    out = decide({"tool_name": tool, "tool_input": {}}, live_settings(settings), TOOLS_X, led, NOW)
    assert _decision(out) == "deny"


def test_guard_leaves_ordinary_mcp_tools_and_allowlist_alone(tmp_path, settings):
    led = LiveLedger(tmp_path / "live.db")
    for tool in ("mcp__gmail__search_threads", "mcp__drive__read_file", "mcp__shop__track_order"):
        assert decide({"tool_name": tool, "tool_input": {}}, settings, TOOLS_X, led, NOW) == {}


def test_guard_still_denies_unclassified_groww_tools(tmp_path, settings):
    led = LiveLedger(tmp_path / "live.db")
    out = decide({"tool_name": "mcp__claude_ai_Groww__get_quote", "tool_input": {}}, settings, TOOLS_X, led, NOW)
    assert _decision(out) == "deny"


def test_load_tools_reads_allow_other(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text("read_only: [a]\norder_tools: {}\nallow_other: [mcp__shop__track_order]\n", encoding="utf-8")
    assert load_tools(p)["allow_other"] == {"mcp__shop__track_order"}


def test_hook_configs_cover_every_mcp_tool():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for f in (root / "hooks" / "hooks.json", root / ".claude" / "settings.json"):
        h = json.loads(f.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
        assert h["matcher"] == "mcp__.*" and "guard" in h["hooks"][0]["command"]
        assert h["hooks"][0]["onFailure"] == "block"


# ---------------------------------------------------------------- runtime check
def _project_with_hook(tmp_path, matcher="mcp__.*"):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": matcher, "hooks": [{"type": "command", "command": "bash scripts/guard.sh"}]}]}}), encoding="utf-8")
    return tmp_path


def test_runtime_needs_claude_code_and_hook(tmp_path):
    proj = _project_with_hook(tmp_path)
    assert runtime_check({"CLAUDECODE": "1"}, proj).ok
    assert not runtime_check({}, proj).ok                                    # Claude app / plain terminal
    assert not runtime_check({"CLAUDECODE": "1"}, tmp_path / "nohook").ok    # no hook configured


def test_runtime_rejects_hook_that_misses_other_connectors(tmp_path):
    proj = _project_with_hook(tmp_path, matcher="mcp__groww__.*")
    assert not runtime_check({"CLAUDECODE": "1"}, proj).ok


def test_approve_requires_send_via():
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["live", "approve", "abc", "--reply", "yes"])
    assert p.parse_args(["live", "approve", "abc", "--reply", "yes", "--send-via", "app"]).send_via == "app"


def test_cli_refuses_claude_send_outside_claude_code(tmp_path, monkeypatch, capsys):
    from india_trading.cli import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    led = LiveLedger(tmp_path / "state" / "live.db")
    t = led.prepare(intent(), "ENTRY", datetime.now(IST))
    rc = main(["--config", "none.yaml", "live", "approve", t["intent_id"], "--reply", "yes", "--send-via", "claude"])
    assert rc == 2 and "REFUSED" in capsys.readouterr().out
    assert led.get(t["intent_id"])["status"] == "PREPARED"


# ---------------------------------------------------------------- app-placed orders
def test_app_approval_is_never_sendable_by_claude_but_recordable(tmp_path, settings):
    s = live_settings(settings)
    led = LiveLedger(tmp_path / "live.db")
    t = led.prepare(intent(), "ENTRY", NOW)
    led.approve(t["intent_id"], "yes", NOW, via="app")
    assert led.get(t["intent_id"])["status"] == "APPROVED_APP"
    assert _decision(decide(call(), s, TOOLS, led, NOW)) == "deny"          # guard never lets Claude send it
    led.record(t["intent_id"], "FILLED", "G9", 2, 95.1)
    assert led.positions()["ABC"]["qty"] == 2


def test_bad_send_via_and_double_approval(tmp_path):
    led = LiveLedger(tmp_path / "live.db")
    t = led.prepare(intent(), "ENTRY", NOW)
    with pytest.raises(LedgerError):
        led.approve(t["intent_id"], "yes", NOW, via="robot")
    led.approve(t["intent_id"], "yes", NOW, via="app")
    with pytest.raises(LedgerError):
        led.approve(t["intent_id"], "yes", NOW, via="claude")              # can't switch to Claude-send later


# ---------------------------------------------------------------- graduation price check
def _bars(tmp_path, sym="ABC", source="yahoo"):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    pd.DataFrame({"date": ["2025-09-22", "2025-09-23"], "open": [100, 101], "high": [102, 103],
                  "low": [99, 100], "close": [101, 102], "volume": [1, 1], "source": [source, source]}
                 ).to_csv(d / f"{sym}.csv", index=False)
    return d


def test_price_inside_the_days_range_is_confirmed(tmp_path):
    d = _bars(tmp_path)
    assert verify_entry_prices([{"symbol": "ABC", "trade_date": "2025-09-22", "price": 101.5}], d) == []
    assert verify_entry_prices([{"symbol": "ABC", "trade_date": "2025-09-22", "price": 102.4}], d) == []  # slippage


@pytest.mark.parametrize("entry,needle", [
    ({"symbol": "ABC", "trade_date": "2025-09-22", "price": 90.0}, "outside"),       # mistyped / invented
    ({"symbol": "ABC", "trade_date": "2025-09-24", "price": 101.0}, "no bar"),       # data not fetched yet
    ({"symbol": "XYZ", "trade_date": "2025-09-22", "price": 101.0}, "no real data"),
    ({"symbol": "ABC", "trade_date": "2025-09-22", "price": None}, "no fill price"),
])
def test_unconfirmed_prices_are_reported(tmp_path, entry, needle):
    probs = verify_entry_prices([entry], _bars(tmp_path))
    assert len(probs) == 1 and needle in probs[0]


def test_synthetic_files_never_confirm(tmp_path):
    d = _bars(tmp_path, source="SYNTHETIC")
    assert verify_entry_prices([{"symbol": "ABC", "trade_date": "2025-09-22", "price": 101}], d)


def test_graduation_fails_on_unconfirmed_prices(settings):
    ids = [f"i{k}" for k in range(30)]
    assert check(settings, _closed(30), ids, _events(ids), price_problems=[]).passed
    g = check(settings, _closed(30), ids, _events(ids), price_problems=["ABC 2025-09-22: ₹90 outside"])
    assert not g.passed and g.stats["unconfirmed_prices"] == 1
