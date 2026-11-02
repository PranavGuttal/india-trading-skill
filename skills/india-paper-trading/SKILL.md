---
name: india-paper-trading
description: >-
  Run the full paper-trading workflow for an NSE stock: analyse, risk-check,
  print an order ticket, ask for an explicit yes, simulate the order, journal
  everything. Use when the user says "paper trade SYMBOL", "simulate a trade",
  "paper status", or "close my paper position". Simulated only.
---

# india-paper-trading

Every order here is SIMULATED in `state/paper.db`. Nothing is sent to Groww.
Always say "paper" or "simulated" when reporting a fill.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" paper start SYMBOL                     # replay: last close, NOT live
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" paper start SYMBOL --price 412.5 --price-source groww-mcp
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" paper start SYMBOL --as-of 2025-09-22  # historical replay
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" paper status
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" paper close SYMBOL --price 420 --price-source groww-mcp
```

## Approval

- The CLI prints the ticket and waits for the user to type `yes`. Show the
  user the ticket and let THEM type yes. Never pass `--approve yes` on the
  user's behalf unless they have just said yes to that exact ticket.
- "ok", "sure", "go", "yes to all" are not approvals.

## Prices

- With no `--price`, the run is a REPLAY using the last CSV close: say so.
- If you read a price through the Groww connector, pass it with
  `--price-source groww-mcp` and state the time you read it.

## Going from paper to a real order

There is no live order path in this release. If the user wants to act on a
ticket in real life, they place it themselves in the Groww app. Remind them
the ticket's numbers are estimates and the ₹200 limit is not enforced by Groww.
