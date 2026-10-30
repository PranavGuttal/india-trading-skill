"""Core data models. Every external input is validated through these."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"   # e.g. timeout: must be reconciled, never blindly retried


TERMINAL = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}


class Quote(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    timestamp: datetime          # timezone-aware
    source: str                  # where it came from: always labelled
    is_delayed: bool = False

    @field_validator("timestamp")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("quote timestamp must be timezone-aware")
        return v


class TradeProposal(BaseModel):
    """What a strategy suggests. Not an order. Must pass the risk manager."""

    decision: Literal["TRADE", "NO_TRADE"]
    symbol: str
    strategy: str
    strategy_version: str
    as_of: datetime
    data_source: str
    reasons: list[str] = Field(default_factory=list)
    contra: list[str] = Field(default_factory=list)
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    max_hold_days: Optional[int] = None

    @model_validator(mode="after")
    def _levels(self) -> "TradeProposal":
        if self.decision == "TRADE":
            if None in (self.entry, self.stop, self.target):
                raise ValueError("a TRADE proposal needs entry, stop and target")
            if not (self.stop < self.entry < self.target):
                raise ValueError("long proposal needs stop < entry < target")
        return self


class OrderIntent(BaseModel):
    """A concrete order the risk manager approved in principle."""

    symbol: str
    side: Side
    qty: int = Field(gt=0)
    limit_price: float = Field(gt=0)
    product: Literal["delivery", "intraday"]
    stop: Optional[float] = None
    target: Optional[float] = None
    proposal_ref: Optional[str] = None
    trade_date: str  # YYYY-MM-DD (IST) — part of idempotency key

    @property
    def intent_id(self) -> str:
        core = {
            "symbol": self.symbol, "side": self.side.value, "qty": self.qty,
            "limit_price": round(self.limit_price, 2), "product": self.product,
            "trade_date": self.trade_date, "proposal_ref": self.proposal_ref,
        }
        blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:20]

    @property
    def value(self) -> float:
        return self.qty * self.limit_price


class RiskDecision(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)   # why blocked (empty if approved)
    warnings: list[str] = Field(default_factory=list)
    qty: int = 0
    est_buy_costs: float = 0.0
    est_roundtrip_costs: float = 0.0
    planned_risk_inr: float = 0.0
    planned_reward_inr: float = 0.0
    intent: Optional[OrderIntent] = None


class Order(BaseModel):
    intent_id: str
    broker_order_id: Optional[str] = None
    symbol: str
    side: Side
    qty: int
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    limit_price: float
    status: OrderStatus
    mode: Literal["paper", "live"]
    message: str = ""
    created_at: datetime
    updated_at: datetime


class Position(BaseModel):
    symbol: str
    qty: int
    avg_price: float
    mode: Literal["paper", "live"]
    stop: Optional[float] = None
    target: Optional[float] = None
    opened_at: datetime
