---
name: india-autopilot
description: >-
  Run the PAPER autopilot: unattended simulated trading over the NSE watchlist
  (exits first, then auto-approved paper entries through the risk manager), a
  day-by-day replay over past data, or a scheduled market-hours loop using
  read-only Groww prices. Use when the user says "run the autopilot", "trade on
  your own (paper)", "simulate how it would have traded", "replay last year",
  or "run every 15 minutes during market hours". Never places real orders.
---

# india-autopilot

Everything here is PAPER. The autopilot refuses any live broker adapter in
code, and paper orders are auto-approved only because they are simulated.
Always say "paper" or "simulated" when reporting what it did.

## Commands (run from the project root)

```bash
python -m india_trading.cli autopilot                         # one replay tick at the last CSV close (NOT live)
python -m india_trading.cli autopilot --prices INFY=1520.5,TCS=3901 --price-source groww-mcp
python -m india_trading.cli replay                            # day-by-day over all data, settings budget
python -m india_trading.cli replay --start 2024-01-01 --capital 20000 --risk 200   # study budget (paper)
python -m india_trading.cli review                            # results of the real paper account
```

`replay` writes to `state/replay/` (trades.csv, equity.csv, journal.db) and
never touches `state/paper.db`.

## One live-price paper tick with Groww (connector enabled)

1. LIST the Groww tools actually available in this chat; read their schemas.
   Never guess tool names. Use only read-only tools (quotes/LTP, holdings,
   positions, charts). Never call a tool that places, modifies or cancels
   an order, even if asked.
2. Read the current price of every watchlist symbol (from `status`/settings)
   and every open paper position (`paper status`). Note the time read.
3. Run `autopilot --prices SYM=PX,... --price-source groww-mcp`.
4. Report exits, entries, blocks with reasons, and the price time. If a
   price had no timestamp, say its time is unknown.

## Scheduling (only if the user asks)

Use `/loop` (or a scheduled task) during NSE hours, 09:15–15:30 IST Mon–Fri,
e.g. every 15–30 minutes, repeating the tick above. Stop when the user says
so, when `kill-switch on` is set, or outside market hours. The computer and
Claude must be running; nothing happens while they are off.

## Reporting results honestly

- At the default ₹200 budget expect zero trades: charges (~₹36 round trip)
  exceed the ₹10 risk limit. Say this is the risk manager working, not a bug.
- `--capital` is a larger PAPER budget to study the strategy. Never present it
  as a suggestion to trade that amount.
- Fewer than 30 closed trades = INCONCLUSIVE. Data in `data/sample/` is
  SYNTHETIC. Say both whenever they apply.
- Compare replay results with `backtest` and say whether both agree.
