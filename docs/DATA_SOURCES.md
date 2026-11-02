# Data sources

**Verified and implemented: local CSV files, and Yahoo Finance's public chart
endpoint for NSE symbols (`data-fetch`, checked 2026-11-01).** NSE's own site
blocks scripted access and is used only through files you download by hand.

| Source | Status | Fields | Latency | Coverage | Symbol / TZ | Terms & limits | Suitable for |
|---|---|---|---|---|---|---|---|
| Yahoo Finance chart API (`data-fetch`) | **Implemented, tested; verified live 2026-11-01** — unofficial | date, OHLC (split-adjusted), volume, dividend & split events | end of day (re-run after 18:00 IST) | 10y daily for NSE stocks (SYMBOL.NS), 17 NSE indices (Nifty 50 `^NSEI`, India VIX, 13 sector indices, Next 50, 500) and index ETFs | NSE symbol + `.NS`, index codes in `yahoo_source.INDICES`; IST | free, personal use, may change or rate-limit | research, backtest, regime, sectors, paper |
| Official NSE index lists (`universe-fetch`, niftyindices.com) | **Implemented, tested; verified 2026-11-02** | company, NSE industry, symbol, series, ISIN for Nifty 50/Next 50/100/200/500, Midcap 150, Smallcap 250 | as published (semi-annual reviews) | current constituents only | NSE symbols | NSE Indices site; one retry on timeout | universes, official sectors |
| NSE website / archives | **Blocked to scripts** (HTTP 403 / no connection from this machine, 2026-11-01) | — | — | — | — | NSE terms; not bypassed | manual download + `data-import` only |
| Local CSV (`data/<SYMBOL>.csv`) | **Implemented, tested** | date, open, high, low, close, volume, optional source | whatever you load (end of day) | whatever you load | NSE symbol; dates are IST trading days | yours | research, backtest, paper replay |
| Synthetic CSV (`scripts/make_sample_data.py`) | **Implemented** — NOT real prices, `source=SYNTHETIC` | as above | n/a | 750 bars from 2023-01-02 | fake symbols `SYNTH_*` | none | tests and demos only |
| Groww MCP connector (in Claude chat) | **Unverified** — tool list not inspected | holdings, positions, P&L, chart data per Groww's 4 Aug 2025 post | unknown | unknown | unknown | Groww terms; OAuth, ~1-day session | possibly research and quotes for paper; quote timestamps must be checked |
| Groww Trade API | **Not configured** | per Groww docs | per docs | intraday 3 months, daily full history per a third-party summary | per docs | ₹499/mo + GST (free trial excludes live data); static IP for orders | future live adapter |
| NSE official bhavcopy / reports | **Not tested** | EOD OHLC, delivery % | end of day | historical archives | NSE symbol + series | NSE website terms; do not scrape against terms | research |

## Rules the code enforces
- Every quote carries `source` and a timezone-aware `timestamp`.
- Delayed quotes, quotes older than `max_quote_age_seconds`, quotes from the
  future, and quotes >2% away from the planned entry are rejected.
- Daily data older than `max_bar_age_days` business days turns a TRADE into NO_TRADE.
- Replay runs label the price `replay:last-close (NOT live)`.
- Validation errors (duplicates, unordered dates, NaNs, non-positive prices,
  high/low inconsistency, **bad ticks**) halt the workflow. >25% one-day moves warn of
  unadjusted splits/bonuses (or real crash days: 2020-03-23 appears in several stocks).
- Bad ticks = 1-3 bar spikes >= 40% away from the surrounding 7-day median that
  revert. Found in Yahoo's ETF data on 2019-12-19/20 (prices at 1/10th), and on
  INDIAMART's Muhurat sessions (2019-10-27, 2020-11-14) and CDSL's listing day
  (2017-06-30), which Yahoo left at 2× because a later 2:1 split was not applied
  to those bars. Nifty 500 download (2026-11-02): 499/501 OK; BAGMANE (new listing)
  is not on Yahoo; DUMMY* rows are NSE placeholders and are skipped.
  `data-fetch` removes them and lists the dates; it never repairs or fills prices.
- Index volume on Yahoo is partly zero (India VIX always); distribution-day
  counts skip those days and no signal uses index volume otherwise.

## Getting real data into the toolkit
1. `python scripts/india.py data-fetch --universe large_caps_20 --indices --etf`
   (or `data-fetch SYMBOL ...`). Stocks → `data/real/` (+ `events/`), indices →
   `data/indices/`, ETFs → `data/etf/`.
2. Or export daily candles you are allowed to use (Groww connector, NSE's
   published files) and `data-import FILE SYMBOL --source <where>`.
3. Point `data_dir: data/real` in `config/settings.yaml`; run `doctor`.

Live prices for decisions come only from what Claude reads with the Groww
connector's read-only tools at that moment (`--prices ... --price-source
groww-mcp`), checked for age by the risk manager. Yahoo data is end of day.

## NSE holiday list
NSE's holiday page could not be read by scripts (timeouts; BSE's page
returned 403, 2026-11-01). `config/nse_holidays.yaml` must be filled by hand
from nseindia.com → Resources → Exchange communication → Holidays. Until a
year is listed, weekday holidays are not detected (the session check may say
"open" on a holiday; quotes will then be stale and the risk manager blocks).
