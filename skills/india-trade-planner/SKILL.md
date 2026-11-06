---
name: india-trade-planner
description: >-
  Plan an NSE delivery trade before taking it: whole-share position size
  for a rupee risk and budget with Groww charges included in the loss,
  entry/stop, 1R-3R targets, break-even after charges, the strategy's exit
  rules (trailing stop, close rules, time stop), optional Monte-Carlo odds;
  and manage open paper positions' exits. Use when the user asks "how many
  shares", "position size", "where should my stop be", "plan this trade",
  "targets", "trailing stop", "when do I exit", or "manage my positions".
---

# india-trade-planner

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" size 412.5 398 --risk 200 --budget 10000
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" plan INFY --data-dir data/real --strategy donchian_trend --risk 500 --budget 20000 --odds
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" plan INFY --data-dir data/real --entry 1500 --stop 1450 --target 1650 --risk 300 --budget 15000
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" exit-plan --data-dir data/real
```

## Rules

- The loss at the stop INCLUDES round-trip charges; that is what the user
  really loses. Quote it, and the break-even price after charges.
- Without `--risk/--budget` the settings' limits apply (1% of the budget
  as risk, the whole budget as max order; see `budget`) and most plans size to 0 shares: explain that charges
  make tiny trades uneconomic rather than suggesting bigger limits.
- A "planning target" (trend strategies) is used for reward checks only; the
  position exits on its trailing stop / close rule instead.
- Gaps can open below the stop: the real loss can be larger. Say so.
- `exit-plan` shows the effective (trailing) stop; the paper autopilot
  raises stored stops itself on its next tick. Stops are never lowered.
- A plan is not approval: entries still go through the risk manager
  (india-paper-trading / india-autopilot). Not advice.
