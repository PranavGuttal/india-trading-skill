# Data sources

**Verified and implemented: local CSV files, and Yahoo Finance's public chart
endpoint for NSE symbols (`data-fetch`, checked 2026-11-01).** NSE's own site
blocks scripted access and is used only through files you download by hand.

| Source | Status | Fields | Latency | Coverage | Symbol / TZ | Terms & limits | Suitable for |
|---|---|---|---|---|---|---|---|
| Yahoo Finance chart API (`data-fetch`) | **Implemented, tested; verified live 2026-11-01** — unofficial | date, OHLC (split-adjusted), volume | end of day (re-run after 18:00 IST) | ~5y+ daily for NSE listings (SYMBOL.NS) | NSE symbol + `.NS`; IST | free, personal use, may change or rate-limit | research, backtest, replay, paper |
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
  high/low inconsistency) halt the workflow. >25% one-day moves warn of
  unadjusted splits/bonuses.

## Getting real data into the toolkit
1. Export or copy daily candles you are allowed to use (e.g. through the
   Groww connector inside Claude, or NSE's published files).
2. Save as `data/real/RELIANCE.csv` with the columns above and `source=<where>`.
3. Point `data_dir: data/real` in `config/settings.yaml`.
4. Run `scan` and check the warnings (adjustments, holidays).

Real-time trading decisions are **disabled** because no verified real-time
source is wired in.
