"""Execution agent: the only code path that can hand an order to a broker.

Rules it enforces regardless of what any strategy or language model says:
  * no RiskDecision.approved -> no order
  * live adapters are refused unless every live switch is on AND a
    per-order approval was given for this exact intent id
  * a timeout is reconciled by asking for order status; it is never retried
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..brokers.base import BrokerAdapter, BrokerError, BrokerTimeout, UnsupportedOperation
from ..config import Settings
from ..journal.store import Journal
from ..models import Order, OrderStatus, RiskDecision


class ExecutionRefused(RuntimeError):
    pass


@dataclass
class Approval:
    intent_id: str
    reply: str

    def is_explicit_yes(self) -> bool:
        r = self.reply.strip().lower()
        return r.startswith("yes") and "all" not in r and "?" not in r


@dataclass
class ExecutionResult:
    order: Optional[Order]
    status: str
    message: str


class ExecutionAgent:
    def __init__(self, settings: Settings, broker: BrokerAdapter, journal: Journal):
        self.s = settings
        self.broker = broker
        self.journal = journal

    @property
    def mode(self) -> str:
        return "live" if self.broker.is_live else "paper"

    def _guard(self, decision: RiskDecision, approval: Optional[Approval]) -> None:
        if not decision.approved or decision.intent is None:
            raise ExecutionRefused("risk manager did not approve this order")
        if self.broker.is_live:
            if not self.s.live_requested:
                raise ExecutionRefused("live trading is disabled (TRADING_MODE/LIVE_TRADING_ENABLED/LIVE_TRADING_ACK)")
            if approval is None:
                raise ExecutionRefused("live order needs an explicit per-order approval")
        if self.s.require_human_approval and (self.broker.is_live or approval is not None):
            if approval is None or approval.intent_id != decision.intent.intent_id:
                raise ExecutionRefused("approval does not match this exact order")
            if not approval.is_explicit_yes():
                raise ExecutionRefused("approval must be an explicit 'yes' for one order")

    def execute(self, decision: RiskDecision, approval: Optional[Approval] = None) -> ExecutionResult:
        self._guard(decision, approval)
        intent = decision.intent
        assert intent is not None
        existing = self.broker.get_order_status(intent.intent_id)
        if existing is not None:
            self.journal.record("RECOVERY", self.mode, "intent already exists at broker; not resubmitting",
                                symbol=intent.symbol, intent_id=intent.intent_id)
            return ExecutionResult(existing, existing.status.value, "duplicate prevented")
        self.journal.record("ORDER_SUBMITTED", self.mode, f"BUY {intent.qty} {intent.symbol} @ {intent.limit_price}",
                            symbol=intent.symbol, intent_id=intent.intent_id, payload=intent.model_dump(mode="json"))
        try:
            order = self.broker.place_order(intent)
        except BrokerTimeout as e:
            # The request may have landed. Ask, do not retry.
            order = self.broker.get_order_status(intent.intent_id)
            msg = f"timeout ({e}); reconciled status: {order.status.value if order else 'NOT FOUND'}"
            self.journal.record("RECOVERY", self.mode, msg, symbol=intent.symbol, intent_id=intent.intent_id)
            if order is None:
                return ExecutionResult(None, OrderStatus.UNKNOWN.value,
                                       msg + " — order state unknown; check the broker manually before doing anything")
            return ExecutionResult(order, order.status.value, msg)
        except UnsupportedOperation as e:
            self.journal.record("ERROR", self.mode, str(e), symbol=intent.symbol, intent_id=intent.intent_id)
            raise
        except BrokerError as e:
            self.journal.record("ERROR", self.mode, f"broker error: {e}", symbol=intent.symbol, intent_id=intent.intent_id)
            return ExecutionResult(None, OrderStatus.UNKNOWN.value, f"broker error: {e}")
        kind = "FILL" if order.filled_qty else "ORDER_STATUS"
        self.journal.record(kind, self.mode, f"{order.status.value}: {order.message}", symbol=order.symbol,
                            intent_id=order.intent_id, payload=order.model_dump(mode="json"))
        return ExecutionResult(order, order.status.value, order.message)
