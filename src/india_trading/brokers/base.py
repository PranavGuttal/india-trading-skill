"""Broker adapter interface. Paper and (future) live adapters implement it.

Any operation an adapter cannot do with VERIFIED documentation must raise
UnsupportedOperation — never guess.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from ..models import Order, OrderIntent, Position, Quote
from ..risk.manager import AccountState


class BrokerError(RuntimeError):
    pass


class UnsupportedOperation(BrokerError):
    pass


class BrokerTimeout(BrokerError):
    """The request may or may not have reached the broker. Reconcile first."""


class BrokerAdapter(ABC):
    name: str = "abstract"
    is_live: bool = False

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_historical_bars(self, symbol: str, days: int) -> pd.DataFrame: ...

    @abstractmethod
    def get_instrument_details(self, symbol: str) -> dict: ...

    @abstractmethod
    def get_account_state(self, trade_date: str) -> AccountState: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_order_status(self, intent_id: str) -> Optional[Order]: ...

    @abstractmethod
    def place_order(self, intent: OrderIntent) -> Order: ...

    @abstractmethod
    def cancel_order(self, intent_id: str) -> Order: ...
