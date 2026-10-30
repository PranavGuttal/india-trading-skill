"""Groww adapter — deliberately NOT wired to any live endpoint in this release.

Why every method raises UnsupportedOperation:

* The Groww MCP server (https://mcp.groww.in/mcp) is a tool server that
  Claude calls inside a chat, after the user signs in through Groww's OAuth
  page. This Python process cannot call it, and its exact tool names and
  schemas were NOT inspected while building this release (the connector was
  not attached to the build session). Guessing them is forbidden.
* The Groww Trade API (https://groww.in/trade-api) is a separate, paid,
  token-based API with static-IP rules for orders. It is not configured here.

How Groww is used instead (see docs/GROWW_INTEGRATION.md):
  1. In Claude, with the Groww connector enabled, the skills list the actual
     MCP tools first and use ONLY read-only ones (holdings, positions, charts).
  2. Data fetched that way can be saved to CSV and fed to this toolkit.
  3. An approved proposal becomes a printed ORDER TICKET (manual_ticket.py)
     that the user places themselves in the Groww app.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..models import Order, OrderIntent, Position, Quote
from ..risk.manager import AccountState
from .base import BrokerAdapter, UnsupportedOperation

_WHY = (
    "not available: Groww capabilities were not verified for this Python adapter. "
    "Use the Groww connector read-only inside Claude, or place orders yourself from the manual ticket. "
    "See docs/GROWW_INTEGRATION.md."
)


class GrowwAdapter(BrokerAdapter):
    name = "groww"
    is_live = True

    def _no(self, op: str):
        raise UnsupportedOperation(f"GrowwAdapter.{op}: {_WHY}")

    def get_quote(self, symbol: str) -> Quote:
        self._no("get_quote")

    def get_historical_bars(self, symbol: str, days: int) -> pd.DataFrame:
        self._no("get_historical_bars")

    def get_instrument_details(self, symbol: str) -> dict:
        self._no("get_instrument_details")

    def get_account_state(self, trade_date: str) -> AccountState:
        self._no("get_account_state")

    def get_positions(self) -> list[Position]:
        self._no("get_positions")

    def get_order_status(self, intent_id: str) -> Optional[Order]:
        self._no("get_order_status")

    def place_order(self, intent: OrderIntent) -> Order:
        self._no("place_order")

    def cancel_order(self, intent_id: str) -> Order:
        self._no("cancel_order")
