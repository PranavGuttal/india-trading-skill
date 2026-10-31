---
name: india-cost-calculator
description: >-
  Show the Groww charge breakdown (brokerage, STT, stamp, exchange, SEBI,
  IPFT, DP, GST), round-trip cost, break-even move and loss-at-stop including
  charges for any NSE trade size. Use when the user asks "how much will
  charges be", "is ₹200 enough", "break-even", "brokerage on this trade", or
  "how many shares can I buy".
---

# india-cost-calculator

```bash
python -m india_trading.cli costs 200                       # 1 share at ₹200, delivery
python -m india_trading.cli costs 50 --qty 4 --stop 48 --target 54
python -m india_trading.cli costs 1500 --qty 2 --product intraday
python -m india_trading.cli risk-status                     # limits used by the risk manager
```

- Charges come from `config/settings.yaml` (copied from groww.in/pricing on
  the `as_of` date it prints). They are estimates; the contract note is the
  source of truth. If the date is old, tell the user to re-verify.
- Explain the arithmetic plainly: ₹5 minimum brokerage per side plus the DP
  charge on delivery sells is why tiny trades are mostly charges.
- Never suggest loosening risk limits so a trade fits. Sizes are decided by
  the risk manager; this tool only explains them.
- NSE trades whole shares only, and the toolkit skips stocks under ₹20, so
  very small amounts (e.g. ₹1) cannot buy anything at all.
