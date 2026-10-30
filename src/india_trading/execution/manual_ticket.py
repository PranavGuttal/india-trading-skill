"""Order ticket for the user to place THEMSELVES in the Groww app."""
from __future__ import annotations

from ..models import RiskDecision, TradeProposal


def render_ticket(proposal: TradeProposal, decision: RiskDecision, mode: str = "paper") -> str:
    if not decision.approved or decision.intent is None:
        lines = [f"NO ORDER for {proposal.symbol}: risk manager blocked it."]
        lines += [f"  - {r}" for r in decision.reasons]
        return "\n".join(lines)
    i = decision.intent
    banner = "PAPER (simulated)" if mode == "paper" else "MANUAL — YOU place this in Groww; nothing is sent automatically"
    return "\n".join([
        f"=== ORDER TICKET [{banner}] ===",
        f"BUY {i.qty} x {i.symbol} (NSE)  LIMIT ₹{i.limit_price:.2f}  product={i.product}",
        f"Stop-loss ₹{i.stop:.2f}   Target ₹{i.target:.2f}   Max hold {proposal.max_hold_days} days",
        f"Order value ₹{i.value:.2f}   Est. buy charges ₹{decision.est_buy_costs:.2f}   Est. round-trip charges ₹{decision.est_roundtrip_costs:.2f}",
        f"Planned max loss (incl. charges) ₹{decision.planned_risk_inr:.2f}   Planned reward after charges ₹{decision.planned_reward_inr:.2f}",
        f"Why: " + "; ".join(proposal.reasons),
        f"Against: " + ("; ".join(proposal.contra) or "none recorded"),
        "Risks: gaps and slippage can make the loss larger than planned; charges are estimates; not advice.",
        f"Strategy {proposal.strategy} v{proposal.strategy_version}; data {proposal.data_source} as of {proposal.as_of.isoformat()}",
        f"intent_id {i.intent_id}",
    ])
