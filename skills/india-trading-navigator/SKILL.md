---
name: india-trading-navigator
description: >-
  Map a trading request to the right india-* skill and command, and explain
  what the toolkit can and cannot do. Use when the user asks "what can you
  do", "how do I start", "which command", "help me trade on NSE/Groww", or
  the request does not clearly match one skill.
---

# india-trading-navigator

| User wants | Skill | Command |
|---|---|---|
| Market open? scan setups | india-market-monitor | `market-check`, `scan` |
| Breadth / regime | india-market-breadth | `breadth` |
| Analyse one stock, backtest | india-trade-research | `analyze`, `backtest` |
| Odds of a specific plan | india-time-machine | `timemachine` |
| Charges, break-even, size | india-cost-calculator | `costs` |
| Why blocked, kill switch | india-risk-manager | `risk-status`, `kill-switch` |
| One paper trade with approval | india-paper-trading | `paper start/close/status` |
| Trade on its own (paper), replay history | india-autopilot | `autopilot`, `replay` |
| Load real data, holidays | india-data-manager | `data-import`, `scan` |
| Journal / export | india-trade-journal | `journal` |
| How am I doing, go live? | india-trade-review | `review` |
| Real-money order (locked) | india-live-trading | `live status/prepare/approve/record` |

All commands: `python -m india_trading.cli <command>` from the project root,
after `pip install -e ".[dev]"`.

## Always true

- Paper by default. Real money only through india-live-trading, which stays
  locked until graduation and needs the user's explicit yes per order.
- The Groww connector is read-only everywhere except the guarded order call
  in india-live-trading; list its tools before using any.
- The risk manager's block is final; never suggest loosening limits.
- `data/sample/` is SYNTHETIC; <30 trades is inconclusive; not advice.
- Suggested first session: `status` → `costs 200` → `scan` →
  `replay --capital 20000 --risk 200` (study budget) → `review`.
