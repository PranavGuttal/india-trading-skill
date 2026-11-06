# India Trading Skill

A Claude Code plugin for **NSE cash equities through Groww**. It has 27 skills
and 6 read-only agents, all on top of a tested Python toolkit:
- **Research:** market regime, sector rotation, a Nifty 500 screener, technical
  and fundamental stock analysis, a portfolio-level strategy lab, a trade planner,
  and agents for news and SEBI circulars, results, FII/DII flows and scenarios.
- **Risk control:** one deterministic risk manager with a capital floor and a
  tested market gate.
- **Trading:** paper trading (by hand, on autopilot, or monthly allocation),
  plus a real-money desk that stays **locked** until the paper account passes
  a graduation test. Every live order needs your explicit yes. Claude may send
  it only from Claude Code, through a guard hook that checks every MCP tool
  call; otherwise you place it yourself in the Groww app. Real-money steps are
  supported in **Claude Code only**: in the Claude desktop/web app there is no
  hook and no persistent paper account (docs/GROWW_INTEGRATION.md).

> **Read this first.** On 10 years of real NSE data, **no strategy in this
> toolkit beat simply buying and holding after Groww's charges**. The
> 200-day trend filter only reduced drawdowns, and it cost return
> (docs/STRATEGY_LAB.md). This is an engineering and learning tool, not a
> money machine and not advice. Most retail traders in India lose money (SEBI).

## Install in Claude Code
```text
/plugin marketplace add C:\Users\<you>\Documents\india-trading-skill
/plugin install india-trading-skill@india-trading
```
Then restart Claude Code so the guard hook loads. In any project folder, ask
Claude: **"set up the India trading toolkit"**. It runs:
- `--setup` once: about 6 minutes, and it downloads pandas, numpy, pydantic,
  PyYAML and tzdata into `%LOCALAPPDATA%\india-trading\venv`, outside the plugin;
- then `doctor`, which lists anything still missing.

From a terminal, the same commands are:
```powershell
python "<plugin folder>\scripts\india.py" --setup
python "<plugin folder>\scripts\india.py" doctor
```
Your data, settings and state live in the **project folder** you work in. The
plugin folder only holds code and reference files.

## What to ask Claude
| Ask | Skill → command |
|---|---|
| "get real data for the top 20 stocks" | india-data-manager → `data-fetch --universe large_caps_20 --indices --etf` |
| "how is the market? risk on?" | india-market-regime → `regime` |
| "which sectors are leading" | india-sector-rotation → `sectors` |
| "find breakout / VCP / momentum stocks" | india-stock-screener → `screen` |
| "technical view on KOTAKBANK" | india-technical-analyst → `technical` |
| "full fundamental + technical view of INFY" | india-stock-analysis |
| "scan the Nifty 500 for breakouts" | india-stock-screener → `universe-fetch NIFTY500`, `screen --universe NIFTY500` |
| "are FIIs selling? any SEBI circular?" | india-news-research (agents) |
| "which strategy works? test them all" | india-strategy-lab → `lab`, `strategies` |
| "plan a trade, how many shares, where's my stop" | india-trade-planner → `plan`, `size`, `exit-plan` |
| "review my Groww holdings" | india-portfolio-manager → `portfolio` |
| "dividends / results for ITC" | india-corporate-actions, india-news-research |
| "alert me if INFY crosses 1600" | india-alerts → `alerts` |
| "trade on your own (paper)" | india-autopilot → `autopilot`, `replay` |
| "a safer monthly ETF strategy (paper)" | india-allocation → `allocate` |
| "run my daily routine" | india-daily-routine → `daily` |
| "why was this blocked / protect my capital" | india-risk-manager |
| "am I ready for real money?" | india-trade-review → `review`, `live status` |

The full map is in `skills/india-trading-navigator/SKILL.md`.

## Protection, in order
1. **Paper by default.** Only `live` commands concern real money, and they are locked.
2. **Risk manager, in code, and its block is final.** It enforces:
   - the budget, the per-order cap, and risk per trade **including charges**;
   - daily, weekly and monthly loss limits, and a cooldown after 3 losses in a row;
   - the **capital floor** (default 90% of the budget), stale-quote checks and the kill switch.
3. **Market gate** (default): no new entries while Nifty 50 is below its
   200-day average, or if its data is stale. On real data it lowered drawdowns
   and losing months for every swing strategy (docs/STRATEGY_LAB.md).
4. **Capital floor.**
   - A trade may never put equity below the floor, even if it hits its stop
     (open positions are valued at their stops).
   - If the floor is breached anyway (gaps), the autopilot sells everything
     and stops.
   - It limits losses; nothing can guarantee them, or a profit.
5. **Graduation, before any real order:** at least 30 paper trades on at least
   20 days, on real data with live-read prices, and positive after charges.
6. **Your explicit yes for each live order.** The approval expires after 5
   minutes and works once.
7. **Guard hook.** Claude Code denies any Groww order tool call that doesn't
   match an approved ticket.

## The money reality
- **Your budget is yours to change.** ₹200 is only the starting value:
  `budget set 5000` raises or lowers it, moves the paper cash by the
  difference, and every limit follows (max order 100%, risk per trade 1%,
  daily loss 3%, capital floor 90% of the budget). `budget` shows the limits
  next to your paper results.
- **₹200:** a delivery round trip costs about ₹36 (18%), so every ₹200 trade
  is blocked. That is the risk manager doing its job (`costs 200`).
- **Below about ₹25,000:** only a single index ETF is economical. A 20-stock
  basket needs about ₹1 lakh.
- **Swing strategies:** they paid ₹30,000–₹83,000 in charges per ₹1 lakh over
  9 years and lost money. Holding the same stocks paid ₹1,232.

## Data
- **History:** Yahoo Finance daily bars for NSE stocks, 17 NSE indices
  (Nifty 50, India VIX, 13 sectors) and index ETFs. It is unofficial and
  end-of-day, with 10 years of history plus dividends and splits.
  Bad ticks are removed and listed.
- **Live prices:** only what Claude reads with the Groww connector's
  read-only tools at that moment.
- **NSE holidays:** you fill `config/nse_holidays.yaml` from NSE's page,
  because it refuses scripts.
- **Synthetic sample:** `data/sample/` is SYNTHETIC test data.

## Tests
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"
python -m pytest
```
The suite covers:
- strategies, indicators and charges;
- the risk manager and capital floor;
- the paper broker, autopilot, replay and lab;
- every CLI command run end to end in a fresh project;
- the live lock and guard hook;
- a contract test that parses every command each SKILL.md tells Claude to run.

## Layout
```
.claude-plugin/    plugin.json, marketplace.json      hooks/       hooks.json (live guard)
skills/            27 skills                           agents/      6 read-only agents
scripts/           india.py (launcher), guard.sh, make_sample_data.py
config/            settings.example.yaml, universes.yaml, sectors.yaml, alerts.example.yaml,
                   nse_holidays.yaml, groww_tools.yaml
src/india_trading/ market_data (csv, yahoo, importer, calendar), indicators, strategies (registry,
                   ma_trend, trend: donchian/template/rsi2, rotation), risk, brokers, execution,
                   backtesting (engine, portfolio, lab), simulation (timemachine, replay),
                   analysis (regime, sectors, screener, technical, planner, portfolio, alerts,
                   actions, breadth), workflows (supervisor, autopilot, allocation),
                   journal, live (graduation, ledger, desk, guard), cli.py
docs/              STRATEGY_LAB, REFERENCE_ANALYSIS, ARCHITECTURE, DATA_SOURCES, RISK_POLICY,
                   GROWW_INTEGRATION, BACKTESTING, OPERATIONS
```

## Not done / not verified
- The Groww connector's tools have not been listed yet, so
  `config/groww_tools.yaml` is empty. Until it is filled, every Groww order
  tool is denied. The live path has never sent a real order.
- The NSE holiday list for 2025, 2026 and 2027 is empty: weekday holidays
  are not detected.
- Fundamentals (earnings growth, valuation) have no verified free data feed:
  the screener covers only the chart half of CANSLIM. Results come through
  the research agents, from the filings, with sources.
- Options and F&O are deliberately not supported. SEBI found about 9 in 10
  F&O traders lose money, and the config refuses derivatives.
- Not modelled: partial fills, circuit limits and price bands,
  ASM/GSM lists, impact cost, and dividends in stock prices.

Credits: ideas from `tradermonty/claude-trading-skills` and
`Jakeschincariol/day-trader-skill` (both MIT). No code was copied. See
`docs/REFERENCE_ANALYSIS.md` for what was adapted and an honest comparison.
