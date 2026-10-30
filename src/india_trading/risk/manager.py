"""Deterministic risk manager. No LLM is consulted. Fails closed.

Every check that cannot be evaluated (missing account state, stale data,
unknown position) BLOCKS the order rather than letting it through.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..models import OrderIntent, Quote, RiskDecision, Side, TradeProposal
from .costs import estimate_charges, roundtrip_costs


@dataclass
class AccountState:
    """Verified snapshot of what the account looks like right now."""

    cash_available: float
    open_positions: int
    pending_orders: int
    realised_pnl_today: float
    trades_today: int
    verified: bool = True
    source: str = "paper"
    open_symbols: set[str] = field(default_factory=set)
    pending_intent_ids: set[str] = field(default_factory=set)


class KillSwitch:
    """A file on disk. If it exists, no new orders. Survives restarts."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def engaged(self) -> bool:
        return self.path.exists()

    def engage(self, reason: str = "manual") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(f"{datetime.now().isoformat()} {reason}\n", encoding="utf-8")

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()


class RiskManager:
    def __init__(self, settings: Settings, kill_switch: Optional[KillSwitch] = None):
        self.s = settings
        self.kill = kill_switch or KillSwitch(settings.state_path("KILL_SWITCH"))

    # ------------------------------------------------------------------ sizing
    def size_position(self, entry: float, stop: float) -> int:
        """Largest whole-share qty within per-trade risk, order cap and budget
        (costs are checked afterwards; qty is reduced until they fit)."""
        per_share_risk = entry - stop
        if per_share_risk <= 0 or entry <= 0:
            return 0
        by_risk = math.floor(self.s.max_risk_per_trade_inr / per_share_risk)
        by_order = math.floor(self.s.max_single_order_value_inr / entry)
        by_budget = math.floor(self.s.max_experimental_allocation_inr / entry)
        return max(0, min(by_risk, by_order, by_budget))

    # ------------------------------------------------------------------ evaluate
    def evaluate(
        self,
        proposal: TradeProposal,
        quote: Optional[Quote],
        account: Optional[AccountState],
        now: datetime,
        trade_date: str,
        session_open: Optional[bool] = None,
    ) -> RiskDecision:
        s = self.s
        block: list[str] = []
        warn: list[str] = []

        if self.kill.engaged:
            return RiskDecision(approved=False, reasons=["kill switch is engaged"])
        if proposal.decision != "TRADE":
            return RiskDecision(approved=False, reasons=["strategy returned NO_TRADE"])

        # --- data quality
        if quote is None:
            return RiskDecision(approved=False, reasons=["no quote available"])
        if quote.symbol != proposal.symbol:
            return RiskDecision(approved=False, reasons=["quote symbol does not match proposal"])
        if quote.is_delayed:
            block.append(f"quote from {quote.source} is delayed; not usable for a decision")
        age = (now - quote.timestamp).total_seconds()
        if age < -5:
            block.append("quote timestamp is in the future (clock or data problem)")
        elif age > s.max_quote_age_seconds:
            block.append(f"quote is stale ({int(age)}s old > {s.max_quote_age_seconds}s)")
        if quote.price < s.min_price_inr:
            block.append(f"price ₹{quote.price:.2f} below penny-stock floor ₹{s.min_price_inr:.2f}")
        drift = abs(quote.price - proposal.entry) / proposal.entry
        if drift > 0.02:
            block.append(f"live price ₹{quote.price:.2f} is {drift:.1%} away from planned entry ₹{proposal.entry:.2f}")
        if quote.price <= proposal.stop:
            block.append("price is already at or below the stop")

        if session_open is False:
            block.append("market session is closed")
        elif session_open is None:
            warn.append("session status not supplied")

        # --- account state
        if account is None or not account.verified:
            block.append("account state could not be verified")
            return RiskDecision(approved=False, reasons=block, warnings=warn)
        if proposal.symbol in account.open_symbols:
            block.append(f"already holding {proposal.symbol}")
        if account.open_positions + account.pending_orders >= s.max_open_positions:
            block.append(f"max open positions reached ({s.max_open_positions})")
        if account.trades_today >= s.max_trades_per_day:
            block.append(f"max trades per day reached ({s.max_trades_per_day})")
        if -account.realised_pnl_today >= s.daily_loss_limit_inr:
            block.append(f"daily loss limit ₹{s.daily_loss_limit_inr:.0f} reached; new trades halted")

        # --- sizing with costs
        entry = max(proposal.entry, quote.price)  # measure risk from the worse price
        stop, target = proposal.stop, proposal.target
        qty = self.size_position(entry, stop)
        buy_costs = rt = 0.0
        while qty > 0:
            value = qty * entry
            buy_costs = estimate_charges(value, "BUY", s.product, s.charges).total
            rt = roundtrip_costs(value, qty * target, s.product, s.charges)
            loss_at_stop = qty * (entry - stop) + rt
            if (value + buy_costs <= min(s.max_experimental_allocation_inr, account.cash_available)
                    and value <= s.max_single_order_value_inr
                    and loss_at_stop <= s.max_risk_per_trade_inr):
                break
            qty -= 1
        if qty <= 0:
            block.append(
                "no whole-share quantity fits the budget, order cap and per-trade risk "
                "once estimated charges are included"
            )
            return RiskDecision(approved=False, reasons=block, warnings=warn)

        risk_inr = qty * (entry - stop) + rt
        reward_gross = qty * (target - entry)
        reward_net = reward_gross - rt
        rr = (target - entry) / (entry - stop)
        if rr < s.min_reward_risk:
            block.append(f"reward:risk {rr:.2f} below minimum {s.min_reward_risk}")
        if reward_gross < s.min_reward_to_cost * rt:
            block.append(
                f"planned gross reward ₹{reward_gross:.2f} is less than {s.min_reward_to_cost}× "
                f"estimated round-trip charges ₹{rt:.2f} — costs would eat the edge"
            )
        if reward_net <= 0:
            block.append("planned reward is negative after charges")
        remaining_today = s.daily_loss_limit_inr + min(0.0, account.realised_pnl_today)
        if risk_inr > remaining_today:
            block.append(f"risk ₹{risk_inr:.2f} exceeds remaining daily loss allowance ₹{remaining_today:.2f}")

        intent = OrderIntent(
            symbol=proposal.symbol, side=Side.BUY, qty=qty, limit_price=round(entry, 2),
            product=s.product, stop=stop, target=target,
            proposal_ref=f"{proposal.strategy}:{proposal.strategy_version}:{proposal.as_of.isoformat()}",
            trade_date=trade_date,
        )
        if intent.intent_id in account.pending_intent_ids:
            block.append("duplicate: an identical order intent is already pending or done today")

        return RiskDecision(
            approved=not block, reasons=block, warnings=warn, qty=qty,
            est_buy_costs=round(buy_costs, 2), est_roundtrip_costs=round(rt, 2),
            planned_risk_inr=round(risk_inr, 2), planned_reward_inr=round(reward_net, 2),
            intent=intent if not block else None,
        )
