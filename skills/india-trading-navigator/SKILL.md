---
name: india-trading-navigator
description: >-
  Map an Indian stock-market (NSE, Groww) request to the right india-* skill
  and command, run first-time setup, and explain what the toolkit can and
  cannot do. Use when the user asks "what can you do", "how do I start",
  "help me trade on NSE/Groww", "set this up", "which command", or the
  request does not clearly match one skill.
---

# india-trading-navigator

Every command runs in the user's project folder as

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" doctor
```

(use `python3` if `python` is not found). First time only:
`python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" --setup` installs the
packages into the plugin's own `.venv`, then run `doctor` and do what it lists.

## Which skill

| The user wants | Skill | Commands |
|---|---|---|
| Set up, check the install | india-setup | `--setup`, `doctor` |
| Real NSE data, indices, ETFs, holidays | india-data-manager | `data-fetch`, `data-import` |
| How is the market? risk-on? | india-market-regime | `regime` |
| Which sectors lead / lag | india-sector-rotation | `sectors` |
| Find stocks / setups (breakout, VCP, momentum) | india-stock-screener | `screen` |
| Chart read of one stock | india-technical-analyst | `technical` |
| Everything about one stock (fundamental + technical) | india-stock-analysis | `technical`, `actions`, agents |
| Nifty 500 / official index lists | india-data-manager | `universe-fetch`, `data-fetch --universe NIFTY500` |
| Analyse + backtest one stock | india-trade-research | `analyze`, `backtest` |
| Which strategy works? compare all | india-strategy-lab | `strategies`, `lab` |
| Size, plan, stop/targets, exits | india-trade-planner | `size`, `plan`, `exit-plan` |
| Odds of a plan | india-time-machine | `timemachine` |
| Charges, break-even | india-cost-calculator | `costs` |
| My holdings: concentration, review | india-portfolio-manager | `portfolio` |
| Dividends, splits, results | india-corporate-actions | `actions` |
| News, SEBI circulars, results, FII/DII flows, scenarios | india-news-research | agents |
| Price / setup alerts | india-alerts | `alerts` |
| Why blocked, kill switch, capital floor, invest more or less | india-risk-manager | `risk-status`, `kill-switch`, `budget`, `budget set N` |
| One paper trade with approval | india-paper-trading | `paper start/close/status` |
| Trade on its own (paper), replay | india-autopilot | `autopilot`, `replay` |
| Monthly ETF / basket / rotation (paper) | india-allocation | `allocate` |
| Morning / evening routine | india-daily-routine | `daily` |
| Journal / export | india-trade-journal | `journal` |
| How am I doing, ready for real money? | india-trade-review | `review`, `live status` |
| Real-money order (locked) | india-live-trading | `live ...` |
| Watchlist-only breadth | india-market-breadth | `breadth` |
| Session open? polling monitor | india-market-monitor | `market-check`, `monitor` |

## Always true

- PAPER by default. Real money only through india-live-trading, locked until
  graduation, with the user's explicit yes per order and the guard hook.
- The Groww connector is read-only everywhere except that guarded order call;
  list its tools before using any. Never guess tool names.
- The risk manager's block is final; never suggest loosening limits. The
  capital floor (default 90% of the budget) stops trading before it is
  crossed, and the market gate allows no new entries while Nifty 50 is below
  its 200-day average. Options/F&O are deliberately not supported.
- Data: Yahoo Finance daily bars (unofficial, end of day); `data/sample/` is
  SYNTHETIC. Fewer than 30 trades is inconclusive. Research, not advice.
- Tested result to state when asked "will it make money": on 10 years of real
  NSE data no strategy here beat simply holding after charges; the trend
  filter only reduced drawdowns (docs/STRATEGY_LAB.md). Never promise profit.
