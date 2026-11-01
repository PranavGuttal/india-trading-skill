"""Graduation test: the evidence required before ANY live order can be prepared.

Computed from the forward PAPER account (state/paper.db) and its journal,
never from backtests or replays. Every paper entry must have been decided on
non-synthetic data with a manually supplied (live-read) price; one synthetic
or replay entry anywhere in the paper account fails graduation until the
account is reset. Minimums come from settings and can only be raised.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings

_TAINTED = ("synthetic", "replay")


@dataclass
class Graduation:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check(settings: Settings, closed: list[dict], buy_intent_ids: list[str], events: list[dict]) -> Graduation:
    """closed: paper closed trades; buy_intent_ids: filled paper BUY orders;
    events: paper journal events (any order)."""
    reasons = []
    approvals = {e["intent_id"]: e for e in events if e["kind"] == "RISK_APPROVED" and e.get("intent_id")}
    approved_by_user = {e["intent_id"] for e in events if e["kind"] == "APPROVED"}
    tainted, unknown = [], []
    for iid in buy_intent_ids:
        ev = approvals.get(iid)
        if ev is None:
            unknown.append(iid)
            continue
        src = f"{ev.get('data_source') or ''} {ev.get('payload') or ''}".lower()
        if any(t in src for t in _TAINTED) or "manual:" not in src:
            tainted.append(iid)
    net = round(sum(float(t["pnl_net"]) for t in closed), 2)
    days = len({t["trade_date"] for t in closed})
    stats = {"closed_trades": len(closed), "net_pnl": net, "distinct_days": days,
             "tainted_entries": len(tainted), "entries_without_record": len(unknown)}
    if len(closed) < settings.graduation_min_trades:
        reasons.append(f"only {len(closed)} closed paper trades (need {settings.graduation_min_trades})")
    if days < settings.graduation_min_days:
        reasons.append(f"trades on only {days} distinct days (need {settings.graduation_min_days})")
    if net <= 0:
        reasons.append(f"paper net P&L after charges is ₹{net} (must be positive)")
    if tainted:
        reasons.append(f"{len(tainted)} paper entries used synthetic/replay data or no live-read price; "
                       "reset state/paper.db and paper trade on real data only")
    if unknown:
        reasons.append(f"{len(unknown)} paper entries have no RISK_APPROVED journal record")
    missing_yes = [i for i in buy_intent_ids if i not in approved_by_user]
    if missing_yes:
        reasons.append(f"{len(missing_yes)} paper entries have no APPROVED journal record")
    return Graduation(passed=not reasons, reasons=reasons, stats=stats)


def format_graduation(g: Graduation) -> str:
    head = "GRADUATION: PASSED (live preparation may be unlocked by the live switches)" if g.passed else \
        "GRADUATION: NOT PASSED — live orders stay locked"
    return "\n".join([head, f"  {g.stats}"] + [f"  - {r}" for r in g.reasons])
