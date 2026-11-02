---
name: india-daily-routine
description: >-
  Run the full daily NSE routine in one go: optional data refresh, market
  regime, sector rotation, watchlist screen, ETF allocation check, alerts,
  open paper positions and their exits, optional paper autopilot tick, risk
  status; saved as a dated Markdown report. Use when the user says "morning
  routine", "end of day review", "daily brief", "run everything", "what's
  happening today", or wants the routine scheduled.
---

# india-daily-routine

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" daily
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" daily --fetch --paper
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" daily --paper --strategy donchian_trend --out reports/daily
```

`--fetch` downloads fresh data first (internet; run after 18:00 IST for the
day's close). `--paper` adds one PAPER autopilot tick at the last closes.
The report is saved to `reports/daily/YYYY-MM-DD.md`.

## Summarise for the user (short)

1. Regime: trend filter ON/OFF and the posture (heuristic).
2. Leading / lagging sectors.
3. Setups on the watchlist worth a `technical` look.
4. Allocation: hold the ETF or cash this month.
5. Alerts and positions near stops; any exits the autopilot took (paper).
6. Risk status: kill switch, floor, today's loss allowance.

A failed step is reported inside the report; mention it. Scheduling: only if
asked, e.g. `/loop` once a day after 18:00 IST or the `schedule` skill.
Everything is end-of-day research and paper simulation. Not advice.
