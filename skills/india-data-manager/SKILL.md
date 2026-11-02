---
name: india-data-manager
description: >-
  Get real NSE data into the toolkit and keep it trustworthy: download daily
  candles for stocks, Nifty/India VIX/sector indices and index ETFs from the
  internet, import exported candle CSVs (NSE, Groww), validate them (bad
  ticks, gaps, unadjusted splits), keep corporate actions, maintain the NSE
  holiday list, and switch from synthetic to real data. Use when the user
  says "get real data", "load data for INFY", "download Nifty", "import this
  CSV", "use real data", "update holidays", or "is my data OK".
---

# india-data-manager

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-fetch INFY TCS RELIANCE
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-fetch --universe large_caps_20 --indices --etf
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" universe-fetch NIFTY500 NIFTY50 NIFTYMIDCAP150
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-fetch --universe NIFTY500
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-fetch
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-import exports/INFY.csv INFY --source nse-historical
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-import groww_infy.csv INFY --source groww-mcp --out data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" scan --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" market-check
```

- Stocks go to `data/real/` (+ `data/real/events/` for dividends/splits),
  indices to `data/indices/` (NIFTY50, INDIAVIX, NIFTYBANK, NIFTYIT, ...),
  ETFs to `data/etf/`. Default history: 10 years. Named lists:
  `config/universes.yaml` (large_caps_20, holdout_25, index_etfs) or OFFICIAL
  NSE index lists from niftyindices.com via `universe-fetch` (NIFTY50,
  NIFTYNEXT50, NIFTY100, NIFTY200, NIFTY500, NIFTYMIDCAP150,
  NIFTYSMALLCAP250) saved to `data/universes/` with NSE's industry for each stock.
- Then set `data_dir: data/real` and the `watchlist` in `config/settings.yaml`.

## Which source

1. `data-fetch` — Yahoo Finance's public chart endpoint (verified
   2026-11-01: NSE, INR, IST, split-adjusted, dividends not adjusted).
   Free, UNOFFICIAL, end-of-day, personal research only. Say this whenever
   its data is used. Re-run after 18:00 IST for the day's close.
2. Groww connector (read-only chart tools) once its tools are listed.
3. `data-import` for files the user downloaded from nseindia.com by hand.
   NSE's site refuses scripts; never try to get around that.

## Rules

- Never invent or "fill in" prices. `data-fetch` REMOVES bad ticks (1-3
  day price spikes that revert, e.g. a feed printing 1/10th of the price)
  and lists the removed dates; the validator refuses files that still
  contain them. Report every removal and warning.
- >25% one-day moves are warnings (real crash days happen; unadjusted
  splits too). Check the corporate actions before trusting them.
- With the Groww connector: list its tools first, use a read-only chart
  tool, save rows to CSV, then `data-import ... --source groww-mcp`.
- Holidays: fill `config/nse_holidays.yaml` only from the official NSE list.
  NSE's page cannot be read by scripts, so ask the user to open
  nseindia.com → Resources → Exchange communication → Holidays and paste the
  equity dates; write exactly those. Never add dates from memory. Until a
  year is listed, say weekday holidays are not detected.
- `data/sample/` is SYNTHETIC. `data/` is git-ignored (licensing), so
  results on it can be reproduced only on this machine.
