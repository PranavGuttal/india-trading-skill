---
name: india-time-machine
description: >-
  Estimate the odds of ONE planned NSE trade before risking anything: 10,000
  Monte-Carlo paths built from the stock's own past daily bars give the chance
  of hitting the target vs the stop, gap risk, time exits and the average
  result after Groww charges. Use when the user asks "what are the odds",
  "will this trade work", "time machine", "simulate this plan", or gives an
  entry/stop/target to test.
---

# india-time-machine

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" timemachine SYMBOL                               # uses the strategy's plan (if TRADE)
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" timemachine SYMBOL --entry 412 --stop 398 --target 440
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" timemachine SYMBOL --qty 1 --hold 10 --paths 10000 --as-of 2025-09-22
```

## How it works (say this in plain words)

Each past day of the stock (last 250 bars by default) becomes a ratio of
open/high/low/close to the previous close. A path draws random past days,
scales them to the current price, and checks: gap below stop → stop →
target, stop first when one day touches both (conservative). Paths that hit
neither exit at the close of the last holding day. Charges for the quantity
come from the Groww schedule.

## Rules for the answer

- Report the printed numbers only; never invent odds.
- It is a simulation from recent history, not a prediction. Results, news,
  circuit limits and regime changes can do things the pool never saw.
- "Leans toward the target" is relative to the break-even hit rate for that
  reward:risk, not 50%. If the average net after charges is negative, say so
  first: at ₹200 sizes charges usually decide the outcome.
- The time machine never approves a trade. Only the risk manager does.
