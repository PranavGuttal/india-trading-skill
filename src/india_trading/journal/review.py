"""Performance review of closed PAPER trades plus the journal's decisions.

Idea from claude-trading-skills' trade-performance-coach / signal-postmortem
(MIT; no code copied). Pure arithmetic on recorded data; no opinions invented.
"""
from __future__ import annotations

from collections import Counter

from ..backtesting.engine import MIN_TRADES_FOR_EVIDENCE
from ..risk.manager import block_reason_key


def review(closed: list[dict], events: list[dict]) -> dict:
    net = [float(t["pnl_net"]) for t in closed]
    charges = sum(float(t["charges"]) for t in closed)
    gross = sum(net) + charges
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    worst = cur = 0
    for x in net:
        cur = cur + 1 if x <= 0 else 0
        worst = max(worst, cur)
    exits = Counter(r.split(":")[1] if r.startswith("autopilot-exit:") else "manual"
                    for r in ((t.get("reason") or "") for t in closed))
    kinds = Counter(e["kind"] for e in events)
    blocks = Counter()
    for e in events:
        if e["kind"] == "RISK_BLOCKED":
            for r in (e["summary"] or "").split("; "):
                blocks[block_reason_key(r)] += 1
    approved_ids = {e["intent_id"] for e in events if e["kind"] == "APPROVED"}
    unapproved = [e for e in events if e["kind"] == "ORDER_SUBMITTED" and e["intent_id"] not in approved_ids]
    return {
        "closed_trades": len(net),
        "net_pnl": round(sum(net), 2), "gross_pnl": round(gross, 2), "charges": round(charges, 2),
        "charges_share_of_gross": round(charges / abs(gross), 2) if gross else None,
        "win_rate": round(len(wins) / len(net), 3) if net else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "expectancy": round(sum(net) / len(net), 2) if net else None,
        "worst_losing_streak": worst,
        "exit_reasons": dict(exits),
        "signals": kinds["SIGNAL"], "no_trades": kinds["NO_TRADE"], "risk_blocked": kinds["RISK_BLOCKED"],
        "top_block_reasons": dict(blocks.most_common(5)),
        "orders_without_approval_event": len(unapproved),
        "errors": kinds["ERROR"], "recoveries": kinds["RECOVERY"],
    }


def format_review(r: dict) -> str:
    n = r["closed_trades"]
    verdict = (f"TOO EARLY: {n} closed trades (< {MIN_TRADES_FOR_EVIDENCE}); keep paper trading before judging."
               if n < MIN_TRADES_FOR_EVIDENCE else
               "LOSING after charges: do not move to real money." if r["net_pnl"] <= 0 else
               "Positive after charges so far; confirm against the backtest's out-of-sample period before anything else.")
    return "\n".join([
        "PAPER REVIEW [simulated trades only]",
        f"Closed trades {n} | net ₹{r['net_pnl']} | gross ₹{r['gross_pnl']} | charges ₹{r['charges']}"
        f" (share of gross {r['charges_share_of_gross']})",
        f"Win rate {r['win_rate']} | avg win {r['avg_win']} | avg loss {r['avg_loss']} | expectancy {r['expectancy']}"
        f" | worst losing streak {r['worst_losing_streak']}",
        f"Exits by reason: {r['exit_reasons'] or 'none'}",
        f"Decisions: signals {r['signals']} | NO_TRADE {r['no_trades']} | risk-blocked {r['risk_blocked']}",
        f"Top block reasons: {r['top_block_reasons'] or 'none'}",
        f"Integrity: orders without an APPROVED event {r['orders_without_approval_event']} | errors {r['errors']}"
        f" | recoveries {r['recoveries']}",
        "VERDICT: " + verdict,
    ])
