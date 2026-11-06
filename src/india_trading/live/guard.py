"""Claude Code PreToolUse hook for Groww MCP tools. The code-level gate for real orders.

    python -m india_trading.live.guard   (reads the hook JSON on stdin)

The hook matcher is `mcp__.*`: the guard sees EVERY MCP tool call, so a
broker connector added under any name is still checked. Decisions, all fail closed:
  * tool listed under `read_only` in config/groww_tools.yaml -> no objection
    (the normal permission prompt still applies)
  * tool listed under `order_tools` -> "ask" ONLY if the live switches are on
    and the call matches one APPROVED, unexpired, unsent ticket in
    state/live.db exactly (symbol, side, qty, limit price); else "deny"
  * any other tool whose name contains "groww" -> "deny" (classify it first)
  * any other MCP tool whose name looks like an order action (place, order,
    buy, sell, trade, modify, cancel, gtt, square off, exit position) -> "deny",
    unless it is listed under `allow_other` (e.g. a non-broker tool with
    "order" in its name)
  * everything else -> no objection
  * any error -> "deny" (and the hook config sets onFailure: block as a backstop)
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

from ..paths import config_file

TOOLS_FILE = Path("config") / "groww_tools.yaml"   # project copy; falls back to the plugin's (see paths.py)
ORDER_LIKE = re.compile(r"(place|order|buy|sell|trade|modify|cancel|gtt|square|exit_?position|smart_?order|basket)",
                        re.IGNORECASE)


def _out(decision: str | None, reason: str = "") -> dict:
    if decision is None:
        return {}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def load_tools(path: Path | None = None) -> dict:
    path = Path(path) if path is not None else config_file("groww_tools.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    raw = raw or {}
    return {"read_only": set(raw.get("read_only") or []), "order_tools": dict(raw.get("order_tools") or {}),
            "allow_other": set(raw.get("allow_other") or [])}


def _action_name(tool_name: str) -> str:
    """mcp__<server>__<tool> -> <tool> (the part that says what it does)."""
    return tool_name.split("__")[-1] if tool_name.startswith("mcp__") else tool_name


def _field(inp: dict, path: str):
    cur = inp
    for part in str(path).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def decide(event: dict, settings, tools: dict, ledger, now: datetime) -> dict:
    name = str(event.get("tool_name", ""))
    if not name.startswith("mcp__"):
        return _out(None)
    if name in tools["read_only"] or name in tools.get("allow_other", set()):
        return _out(None)
    spec = tools["order_tools"].get(name)
    if spec is None:
        if "groww" in name.lower():
            return _out("deny", f"{name} is not classified in config/groww_tools.yaml. List the Groww tools, read "
                                "this tool's schema, and classify it as read_only or order_tools first.")
        if ORDER_LIKE.search(_action_name(name)):
            return _out("deny", f"{name} looks like an order action from a connector that is not classified in "
                                "config/groww_tools.yaml. If it is a broker tool, classify it; if it is harmless "
                                "(not a broker), list it under allow_other.")
        return _out(None)
    if not settings.live_requested:
        return _out("deny", "live trading is locked (live switches off). Paper only.")
    inp = event.get("tool_input") or {}
    sym, side, qty, price = (_field(inp, spec.get(k, "")) for k in ("symbol", "side", "qty", "price"))
    side_map = {str(v).upper(): k for k, v in (spec.get("side_values") or {"BUY": "BUY", "SELL": "SELL"}).items()}
    side_norm = side_map.get(str(side).upper())
    if sym is None or side_norm is None or qty is None:
        return _out("deny", f"could not read symbol/side/qty from {name} input using the mapping in groww_tools.yaml")
    try:
        qty_i, price_f = int(qty), (None if price is None else float(price))
    except (TypeError, ValueError):
        return _out("deny", "quantity or price is not a number")
    ticket, why = ledger.consume(str(sym).upper(), side_norm, qty_i, price_f, now, settings.live_approval_ttl_seconds)
    if ticket is None:
        return _out("deny", why)
    return _out("ask", f"REAL MONEY: {side_norm} {qty_i} {sym} @ ₹{price_f} matches approved live ticket "
                       f"{ticket['intent_id']}. Confirm only if this is exactly the order you approved.")


def main() -> int:
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR")
        if root:
            os.chdir(root)
        from ..config import load_settings
        from ..market_data.calendar import IST
        from .ledger import LiveLedger

        event = json.loads(sys.stdin.read() or "{}")
        settings = load_settings("config/settings.yaml")
        result = decide(event, settings, load_tools(), LiveLedger(settings.state_path("live.db")), datetime.now(IST))
    except Exception as e:  # fail closed
        result = _out("deny", f"live guard error ({type(e).__name__}: {e}); blocked")
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
