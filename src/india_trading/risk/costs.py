"""Deterministic estimate of Indian cash-equity charges (Groww schedule by default).

These are ESTIMATES from a configurable schedule. Contract notes are the
source of truth; reconcile after every real trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..config import ChargeSchedule


@dataclass(frozen=True)
class ChargeBreakdown:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    ipft: float
    stamp: float
    dp: float
    gst: float

    @property
    def total(self) -> float:
        return round(
            self.brokerage + self.stt + self.exchange + self.sebi + self.ipft
            + self.stamp + self.dp + self.gst, 2
        )


def _brokerage(value: float, s: ChargeSchedule) -> float:
    if value <= 0:
        return 0.0
    return max(s.brokerage_min_inr, min(s.brokerage_cap_inr, value * s.brokerage_pct))


def estimate_charges(
    value: float,
    side: Literal["BUY", "SELL"],
    product: Literal["delivery", "intraday"],
    s: ChargeSchedule,
) -> ChargeBreakdown:
    if value < 0:
        raise ValueError("order value cannot be negative")
    brok = _brokerage(value, s)
    if product == "delivery":
        stt = value * s.stt_delivery_pct
        stamp = value * s.stamp_delivery_buy_pct if side == "BUY" else 0.0
        if side == "SELL":
            dp = s.dp_charge_depository_inr + (0.0 if value < s.dp_broker_waiver_below_inr else s.dp_charge_broker_inr)
        else:
            dp = 0.0
    else:
        stt = value * s.stt_intraday_sell_pct if side == "SELL" else 0.0
        stamp = value * s.stamp_intraday_buy_pct if side == "BUY" else 0.0
        dp = 0.0
    exch = value * s.exchange_txn_pct_nse
    sebi = value * s.sebi_turnover_pct
    ipft = value * s.ipft_pct_nse
    gst = (brok + exch + sebi + ipft + dp) * s.gst_pct
    return ChargeBreakdown(
        round(brok, 4), round(stt, 4), round(exch, 4), round(sebi, 4),
        round(ipft, 4), round(stamp, 4), round(dp, 4), round(gst, 4),
    )


def roundtrip_costs(entry_value: float, exit_value: float, product: Literal["delivery", "intraday"], s: ChargeSchedule) -> float:
    return round(
        estimate_charges(entry_value, "BUY", product, s).total
        + estimate_charges(exit_value, "SELL", product, s).total,
        2,
    )
