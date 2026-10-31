# India Trading Skill

A research, risk-control and **paper-trading** toolkit for NSE cash equities,
with 12 Claude skills and 2 read-only review agents on top. It analyses stocks
with deterministic Python, refuses trades its risk manager does not like,
simulates orders (by hand or on autopilot), replays history day by day, and
keeps a journal. **It cannot place real orders.** Real orders, if you choose to
make them, are placed by you in the Groww app from a printed ticket.

> This is an engineering and learning project, not advice and not a way to
> make ₹100 a day. Most retail intraday traders in India lose money (SEBI).

## What works (tested: 107 automated tests pass)
- Load + validate daily OHLCV CSVs (duplicates, NaNs, OHLC consistency, stale data, split-like jumps); **importer** for NSE/Groww candle exports
- Indicators: SMA, EMA, RSI, MACD, ATR, relative volume, VWAP, support/resistance — tested, causal
- Strategy `ma_trend_pullback` v1.0.0 with explicit rules; returns TRADE or NO_TRADE with reasons
- Groww charge model (from groww.in/pricing, 2026-10-30) and a `costs` calculator with break-even
- Deterministic risk manager (budget, order cap, risk incl. charges, daily/**weekly/monthly** loss limits, **losing-streak cooldown**, positions, duplicates, stale quotes, kill switch) — fails closed
- Paper broker on SQLite: idempotent orders, fills/partials/rejections, cash & positions, restart recovery, timeout reconciliation
- **Paper autopilot**: unattended ticks that manage exits (stop, target, close < SMA50, max hold) then auto-approve paper entries through the same risk manager; refuses any live adapter
- **Day-by-day replay** of the autopilot over history, in its own state folder
- **Time machine**: 10,000-path Monte-Carlo odds of one plan (target vs stop vs gap vs time) after charges
- **Watchlist breadth / regime** (RISK_ON/NEUTRAL/RISK_OFF), optional entry gate
- **Performance review** of paper trades + journal integrity, with the 30-trade rule
- Backtester: next-bar fills, same risk manager, charges, slippage, train/test split, baseline, honest verdicts
- Read-only monitor with heartbeat, stop file and kill switch
- CLI, 12 skills, 2 agents, Claude Code plugin manifest

## Not done / not verified
- **No live order path.** `GrowwAdapter` raises `UnsupportedOperation` for everything.
- Groww MCP tool names/schemas were not inspected (connector not attached during the build).
- No verified real-time or free NSE data source; sample data is **synthetic**.
- NSE holiday list is empty until you fill it from the official circular.
- Breadth is of your watchlist only; no verified Nifty breadth / India VIX source.
- Instrument eligibility (series, ASM/GSM, price bands) is not checked.
- Not modelled: partial fills in backtests, circuit limits, corporate actions.

## The ₹200 reality
At Groww's published charges a ₹200 delivery round trip costs ≈ ₹36 (≈18%)
(`python -m india_trading.cli costs 200`). The per-trade risk limit includes
charges, so **every ₹200 trade is blocked** — in paper, in the backtest and in
the replay. That is the risk manager doing its job. Use a larger *paper*
budget (`--capital`) only to study the strategy. See `docs/RISK_POLICY.md`.

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
`.venv` holds the Python packages the skills' commands need; it is git-ignored.
Run every command from the project root.

## Try it
```powershell
python -m india_trading.cli status
python -m india_trading.cli costs 200
python -m india_trading.cli scan
python -m india_trading.cli breadth
python -m india_trading.cli analyze SYNTH_CHOP --as-of 2025-09-22
python -m india_trading.cli timemachine SYNTH_TREND --entry 150 --stop 143 --target 164 --qty 10
python -m india_trading.cli backtest SYNTH_TREND --capital 20000 --risk 200
python -m india_trading.cli replay --capital 20000 --risk 200     # autopilot day by day (paper)
python -m india_trading.cli autopilot                             # one paper tick at the last close
python -m india_trading.cli paper start SYNTH_CHOP --as-of 2025-09-22      # blocked at ₹200
python -m india_trading.cli review
python -m india_trading.cli journal
python -m india_trading.cli kill-switch on
```

Example on the SYNTHETIC sample (not real prices): `replay --capital 20000
--risk 200` → 750 days, 54 paper trades, net ₹-2,370.95 after ₹2,276.44
charges, verdict NO EDGE SHOWN. At ₹200: 291 signals, all blocked, 0 trades.

## Using it from Claude with Groww
1. Install the skills and agents, either:
   - as a plugin in Claude Code: `/plugin marketplace add <path to this folder>`
     then `/plugin install india-trading-skill@india-trading`, or
   - by copying `skills/*` into `%USERPROFILE%\.claude\skills\` and
     `agents/*` into `%USERPROFILE%\.claude\agents\`.
   The skills run this project's CLI, so open Claude Code **in this folder**
   with the venv set up.
2. Optionally enable the Groww connector (`https://mcp.groww.in/mcp`).
   The skills tell Claude to list its tools first and use **read-only** ones.
3. Ask: "what can you do", "scan my watchlist", "analyse INFY", "what are the
   odds of this plan", "run the paper autopilot every 15 minutes during market
   hours", "replay last year", "how am I doing".

## Skills and agents
| Skill | Does |
|---|---|
| india-trading-navigator | maps a request to the right skill/command |
| india-market-monitor | session status, watchlist scan, read-only Groww holdings/positions |
| india-market-breadth | watchlist breadth and regime |
| india-trade-research | analyse one stock; backtest |
| india-time-machine | Monte-Carlo odds of one plan |
| india-cost-calculator | Groww charges, break-even, loss at stop |
| india-risk-manager | limits, why blocked, kill switch |
| india-paper-trading | one paper trade with explicit approval |
| india-autopilot | unattended paper ticks, replay, market-hours loop |
| india-data-manager | import real data, holidays, validation |
| india-trade-journal | journal and export |
| india-trade-review | performance review, "should I go live?" checklist |

Agents (read-only): `india-strategy-critic` (second opinion on any result),
`india-risk-auditor` (settings, journal and guard audit).

## Layout
```
.claude-plugin/    plugin.json, marketplace.json
agents/            2 read-only review agents
config/            settings.example.yaml, nse_holidays.yaml
skills/            12 Claude skills (SKILL.md)
src/india_trading/ market_data, indicators, strategies, risk, brokers, execution,
                   backtesting, simulation (timemachine, replay), analysis (breadth),
                   monitoring, journal (store, review), workflows (supervisor, autopilot), cli.py
tests/             unit / integration / safety
docs/              REFERENCE_ANALYSIS, ARCHITECTURE, DATA_SOURCES, RISK_POLICY,
                   GROWW_INTEGRATION, BACKTESTING, OPERATIONS
scripts/           make_sample_data.py (SYNTHETIC data)
```

## Roadmap (priority order)
1. Fill `config/nse_holidays.yaml`; load real adjusted NSE daily data into `data/real/` (`data-import`).
2. Backtest + replay on 20+ real liquid stocks; keep the strategy only if test-period results are positive after charges.
3. Inspect the Groww connector's tools; document them in `GROWW_INTEGRATION.md`.
4. Market-regime gate on Nifty breadth / India VIX once a verified source exists.
5. Only after weeks of reviewed paper trading: consider a verified, audited live adapter.

Credits: ideas from `tradermonty/claude-trading-skills` and
`Jakeschincariol/day-trader-skill` (both MIT). No code copied. See `docs/REFERENCE_ANALYSIS.md`.
