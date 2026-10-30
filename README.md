# India Trading Skill

A research, risk-control and **paper-trading** toolkit for NSE cash equities,
with Claude skills on top. It analyses stocks with deterministic Python,
refuses trades its risk manager does not like, simulates orders, and keeps a
journal. **It cannot place real orders.** Real orders, if you choose to make
them, are placed by you in the Groww app from a printed ticket.

> This is an engineering and learning project, not advice and not a way to
> make ₹100 a day. Most retail intraday traders in India lose money (SEBI).

## What works (tested: 81 automated tests pass)
- Load + validate daily OHLCV CSVs (duplicates, NaNs, OHLC consistency, stale data, split-like jumps)
- Indicators: SMA, EMA, RSI, MACD, ATR, relative volume, VWAP, support/resistance — tested, causal
- Strategy `ma_trend_pullback` v1.0.0 with explicit rules; returns TRADE or NO_TRADE with reasons
- Groww charge model (from groww.in/pricing, 2026-10-30): brokerage min/cap, STT, stamp, exchange, SEBI, IPFT, DP, GST
- Deterministic risk manager (budget, order cap, risk incl. charges, daily loss, positions, duplicates, stale quotes, kill switch) — fails closed
- Paper broker on SQLite: idempotent orders, fills/partials/rejections, cash & positions, restart recovery, timeout reconciliation
- Order ticket + explicit per-order "yes" approval
- Journal of every decision with secret redaction and CSV export
- Backtester: next-bar fills, same risk manager, charges, slippage, train/test split, baseline, honest verdicts
- Read-only monitor with heartbeat, stop file and kill switch
- CLI + 5 Claude skills

## Not done / not verified
- **No live order path.** `GrowwAdapter` raises `UnsupportedOperation` for everything.
- Groww MCP tool names/schemas were not inspected (connector not attached during the build).
- No verified real-time or free NSE data source; sample data is **synthetic**.
- NSE holiday list is empty until you fill it from the official circular.
- Instrument eligibility (series, ASM/GSM, price bands) is not checked.
- Not modelled: partial fills in backtests, circuit limits, corporate actions.

## The ₹200 reality
At Groww's published charges a ₹200 delivery round trip costs ≈ ₹36 (≈18%).
The per-trade risk limit includes charges, so **every ₹200 trade is blocked**.
That is the risk manager doing its job. Use a larger *paper* budget
(`--capital`) to study the strategy itself. See `docs/RISK_POLICY.md`.

## Setup (Windows, PowerShell)
```powershell
cd $HOME\Documents\india-trading-skill
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy config\settings.example.yaml config\settings.yaml
python -m pytest                 # run all tests
```
(macOS/Linux: `source .venv/bin/activate`, `cp` instead of `copy`.)

## Try it
```powershell
python -m india_trading.cli status
python -m india_trading.cli scan
python -m india_trading.cli analyze SYNTH_CHOP --as-of 2025-09-22
python -m india_trading.cli backtest SYNTH_TREND
python -m india_trading.cli backtest SYNTH_TREND --capital 20000 --risk 200
python -m india_trading.cli paper start SYNTH_CHOP --as-of 2025-09-22      # blocked at ₹200
python -m india_trading.cli paper status
python -m india_trading.cli journal
python -m india_trading.cli risk-status
python -m india_trading.cli kill-switch on
python -m india_trading.cli monitor start --interval 60 --ticks 1
```

## Using it from Claude with Groww
1. Copy the folders in `skills/` into `%USERPROFILE%\.claude\skills\` (Claude Code)
   or upload them as skills in the Claude app.
2. Optionally enable the Groww connector (`https://mcp.groww.in/mcp`).
   The skills tell Claude to list its tools first and use **read-only** ones.
3. Ask: "scan my watchlist", "analyse INFY", "paper trade INFY at the
   current Groww price", "show my journal".

## Layout
```
config/            settings.example.yaml, nse_holidays.yaml
skills/            5 Claude skills (SKILL.md)
src/india_trading/ market_data, indicators, strategies, risk, brokers,
                   execution, backtesting, monitoring, journal, workflows, cli.py
tests/             unit / integration / safety
docs/              REFERENCE_ANALYSIS, ARCHITECTURE, DATA_SOURCES, RISK_POLICY,
                   GROWW_INTEGRATION, BACKTESTING, OPERATIONS
scripts/           make_sample_data.py (SYNTHETIC data)
```

## Roadmap (priority order)
1. Fill `config/nse_holidays.yaml`; load real adjusted NSE daily data into `data/real/`.
2. Backtest on 20+ real liquid stocks; keep the strategy only if test-period results are positive after charges.
3. Inspect the Groww connector's tools; document them in `GROWW_INTEGRATION.md`; add read-only quote/positions import.
4. Losing-streak cooldown and weekly/monthly drawdown halts (TraderMonty's circuit breaker idea).
5. Market-regime gate (Nifty breadth, India VIX) once a verified source exists.
6. Monte-Carlo replay ("time machine" idea from day-trader-skill).
7. Only after weeks of reviewed paper trading: consider a verified, audited live adapter.

Credits: ideas from `tradermonty/claude-trading-skills` and
`Jakeschincariol/day-trader-skill` (both MIT). No code copied. See `docs/REFERENCE_ANALYSIS.md`.
