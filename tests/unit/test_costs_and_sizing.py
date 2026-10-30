import pytest

from india_trading.config import ChargeSchedule
from india_trading.risk.costs import estimate_charges, roundtrip_costs
from india_trading.risk.manager import RiskManager

S = ChargeSchedule()


def test_brokerage_min_cap_and_pct():
    assert estimate_charges(200, "BUY", "delivery", S).brokerage == 5.0       # 0.1% = 0.2 -> min ₹5
    assert estimate_charges(10_000, "BUY", "delivery", S).brokerage == 10.0   # 0.1%
    assert estimate_charges(100_000, "BUY", "delivery", S).brokerage == 20.0  # cap ₹20


def test_delivery_buy_breakdown_200():
    c = estimate_charges(200, "BUY", "delivery", S)
    assert c.stt == pytest.approx(0.2)
    assert c.stamp == pytest.approx(0.03)
    assert c.dp == 0.0
    # gst on brokerage + exchange + sebi + ipft
    assert c.gst == pytest.approx((5 + 200 * 0.0000297 + 200 * 0.000001 + 200 * 0.000001) * 0.18, abs=1e-4)


def test_delivery_sell_dp_waiver_below_100():
    small = estimate_charges(90, "SELL", "delivery", S)
    big = estimate_charges(150, "SELL", "delivery", S)
    assert small.dp == 3.5
    assert big.dp == 20.0


def test_intraday_has_no_dp_and_sell_side_stt():
    b = estimate_charges(1000, "BUY", "intraday", S)
    s = estimate_charges(1000, "SELL", "intraday", S)
    assert b.stt == 0 and s.stt == pytest.approx(0.25) and s.dp == 0


def test_roundtrip_on_200_is_a_large_share_of_capital():
    rt = roundtrip_costs(200, 200, "delivery", S)
    assert rt > 30  # ~17% of a ₹200 position: the core constraint of a tiny budget


def test_negative_value_rejected():
    with pytest.raises(ValueError):
        estimate_charges(-1, "BUY", "delivery", S)


def test_position_size_respects_risk_order_and_budget(settings):
    rm = RiskManager(settings)
    # risk ₹10 / ₹1 per share = 10 ; order cap 200/50 = 4 ; budget 4
    assert rm.size_position(50, 49) == 4
    assert rm.size_position(50, 52) == 0       # stop above entry
    assert rm.size_position(500, 490) == 0     # cannot afford one share
