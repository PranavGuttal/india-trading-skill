---
name: india-data-manager
description: >-
  Get real NSE daily data into the toolkit and keep it trustworthy: import an
  exported candle CSV (NSE historical data, Groww chart data) into
  data/real/SYMBOL.csv, validate it, maintain the NSE holiday list, and
  switch the toolkit from synthetic to real data. Use when the user says
  "load data for INFY", "import this CSV", "use real data", "update
  holidays", or "is my data OK".
---

# india-data-manager

```bash
python -m india_trading.cli data-import exports/INFY.csv INFY --source nse-historical
python -m india_trading.cli data-import groww_infy.csv INFY --source groww-mcp --out data/real
python -m india_trading.cli scan --data-dir data/real          # validation warnings per file
python -m india_trading.cli market-check                      # holiday-list status
```

Then set `data_dir: data/real` and the `watchlist` in `config/settings.yaml`.

## Rules

- Use only data the user is allowed to use. Never scrape a site against its
  terms. Never invent or "fill in" prices; a missing column is an error.
- Prefer split/bonus-ADJUSTED daily data. The validator warns on >25%
  one-day moves (unadjusted corporate actions?): report every warning.
- With the Groww connector: list its tools first, use a read-only chart/candle
  tool, save the rows to a CSV, then `data-import ... --source groww-mcp`.
- Holidays: fill `config/nse_holidays.yaml` only from the official NSE
  circular (nseindia.com → Resources → Exchange communication → Holidays).
  Do not add dates from memory. Until a year is listed, say weekday holidays
  are not detected.
- `data/sample/` is SYNTHETIC. `data/real/` is git-ignored (licensing), so
  results on it can be reproduced only on this machine.
