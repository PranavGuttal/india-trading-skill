---
name: india-risk-manager
description: >-
  Explain and check the deterministic risk limits: budget, order cap,
  per-trade risk including charges, daily/weekly/monthly loss limits,
  losing-streak cooldown, capital floor, positions, duplicates, stale data,
  kill switch. Use when the user asks "risk status", "why was this
  blocked", "can I take this trade", "don't let me lose more than X",
  "protect my capital", "stop all trading", or "kill switch".
---

# india-risk-manager

The risk manager is code (`src/india_trading/risk/manager.py`). You cannot
override it, and you must not suggest editing limits to get a trade through.
A BLOCK is final for that order.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" risk-status
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" kill-switch on --reason "stepping away"
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" kill-switch off
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" status
```

## What it blocks (fails closed)

kill switch on · NO_TRADE · no/stale/future/delayed quote · price >2% from
plan · price under ₹20 · session closed · account not verified · already
holding · max positions · max trades/day · daily/weekly/monthly loss reached
· 3 losses in a row → 2-business-day cooldown · no whole-share qty fits
budget/order cap/risk after charges · reward:risk < 1.5 · reward < 2×
round-trip charges · risk over the remaining loss allowance · **capital
floor** · **market gate** (Nifty 50 below its 200-day average, or its data
missing/stale) · duplicate intent.

## Capital floor (`capital_floor_pct`, default 90)

- A new trade is allowed only if losing it at its stop, charges included,
  still leaves equity above the floor, with every open position valued at
  ITS stop. With ₹10,000 and a 90% floor, at most ₹1,000 can ever be at risk.
- If equity is found below the floor (a gap through a stop can do that),
  the paper autopilot and allocation pilot sell everything and engage the
  kill switch. Releasing it is the user's decision (`kill-switch off`).
- Be honest: a floor limits losses, it cannot guarantee them. Gaps,
  slippage and charges can push a real loss past the stop. Nothing here can
  guarantee a profit.

## Say this honestly

- The budget is enforced by this app only. Groww does not ring-fence it:
  anything else in the account is reachable with the same login.
- Charges come from settings (Groww pricing copied on 2026-10-30); the
  contract note is the source of truth.
