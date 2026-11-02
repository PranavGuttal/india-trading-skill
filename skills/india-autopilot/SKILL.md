---
name: india-autopilot
description: >-
  Run the PAPER autopilot: unattended simulated swing trading over the NSE
  watchlist with any signal strategy (capital floor first, then exits with
  trailing stops, then auto-approved paper entries through the risk
  manager), a day-by-day replay over past data, or a scheduled market-hours
  loop using read-only Groww prices. Use when the user says "run the
  autopilot", "trade on your own (paper)", "don't ask me, just trade
  (paper)", "simulate how it would have traded", "replay last year", or
  "run every 15 minutes". Never places real orders.
---

# india-autopilot

Everything here is PAPER. The autopilot refuses any live broker adapter in
code, and paper orders are auto-approved only because they are simulated.
Always say "paper" or "simulated" when reporting what it did.

## Commands (run in the user's project folder)

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" autopilot
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" autopilot --strategy donchian_trend
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" autopilot --prices INFY=1520.5,TCS=3901 --price-source groww-mcp
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" replay
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" replay --strategy trend_template --start 2024-01-01 --capital 20000 --risk 200
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" exit-plan
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" review
```

Without `--prices`, a tick uses the last CSV close (a replay tick, NOT live).
`replay` writes to `state/replay/` and never touches `state/paper.db`. The
strategy comes from `strategy:` in settings unless `--strategy` is given;
monthly ETF/basket strategies run through india-allocation instead.

## Order of each tick

1. Capital floor: equity below `capital_floor_pct` of the budget → sell
   everything, engage the kill switch, stop.
2. Exits: gap below stop, stop (raised by the strategy's trailing stop),
   target (if the strategy takes profit), close rules, max hold.
3. Market gate (default): no new entries while Nifty 50 is below its
   200-day average or its data is stale; then entries through the risk manager.

## One live-price paper tick with Groww (connector enabled)

1. LIST the Groww tools in this chat; read their schemas. Never guess names.
   Use only read-only tools (quotes/LTP, holdings, positions, charts).
   Never call a tool that places, modifies or cancels an order.
2. Read the current price of every watchlist symbol and every open paper
   position (`paper status`). Note the time read.
3. Run `autopilot --prices SYM=PX,... --price-source groww-mcp`.
4. Report exits, entries, blocks with reasons, trailing-stop changes and
   the price time.

## Scheduling (only if the user asks)

Use `/loop` during NSE hours, 09:15-15:30 IST Mon-Fri, e.g. every 15-30
minutes, repeating the tick above. Stop when the user says so, when the kill
switch is on, or outside market hours. Claude and the computer must be on.

## Reporting results honestly

- At the default ₹200 budget expect zero trades: charges exceed the ₹10
  risk limit. Say this is the risk manager working, not a bug.
- `--capital` is a larger PAPER budget to study the strategy, never a
  suggestion to trade that amount.
- Fewer than 30 closed trades = INCONCLUSIVE. `data/sample/` is SYNTHETIC.
- The strategy lab found no swing strategy that beat buy & hold after
  charges on real NSE data; the autopilot is for learning and for the
  graduation test, not a money machine. Compare replay with `lab`/`backtest`.
