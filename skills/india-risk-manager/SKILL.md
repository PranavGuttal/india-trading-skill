---
name: india-risk-manager
description: >-
  Explain and check the deterministic risk limits: budget, order cap, per-trade
  risk including charges, daily loss limit, positions, duplicates, stale data,
  kill switch. Use when the user asks "risk status", "why was this blocked",
  "can I take this trade", "stop all trading", or "kill switch".
---

# india-risk-manager

The risk manager is code (`src/india_trading/risk/manager.py`). You cannot
override it, and you must not suggest editing limits to get a trade through.
A BLOCK is final for that order.

```bash
python -m india_trading.cli risk-status
python -m india_trading.cli kill-switch on --reason "stepping away"
python -m india_trading.cli kill-switch off
python -m india_trading.cli status
```

## What it blocks (fails closed)

kill switch on · NO_TRADE · no/stale/future/delayed quote · price >2% from
plan · price under ₹20 · session closed · account not verified · already
holding · max positions · max trades/day · daily loss reached · no whole-share
qty fits budget/order cap/risk after charges · reward:risk < 1.5 · reward <
2× round-trip charges · risk over today's remaining allowance · duplicate intent.

## Say this honestly

- The ₹200 budget is enforced by this app only. Groww does not ring-fence
  it: anything else in the account is reachable with the same login.
- Gaps, slippage and charges can make a real loss larger than planned.
- Charges come from `config/settings.yaml` (Groww pricing copied on
  2026-10-30); the contract note is the source of truth.
