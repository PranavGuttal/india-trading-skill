---
name: india-trade-research
description: >-
  Analyse one NSE stock with a deterministic strategy (ma_trend_pullback,
  donchian_trend, trend_template or rsi2_reversion) and backtest it on that
  stock with Indian (Groww) charges. Use when the user says "analyse
  SYMBOL", "should this setup work", "backtest SYMBOL", "how did this
  strategy do on X", or asks for entry/stop/target levels. Returns TRADE or
  NO_TRADE with reasons for and against.
---

# india-trade-research

All indicator maths is done by Python, never in your head. Report the
numbers the tool prints; do not invent any.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" analyze INFY --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" analyze INFY --data-dir data/real --strategy donchian_trend --as-of 2025-09-22
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" backtest INFY --data-dir data/real --capital 20000 --risk 200
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" backtest INFY --data-dir data/real --strategy trend_template --capital 20000 --risk 200 --out reports/trades.csv
```

`strategies` lists them with their rules. For a whole-universe comparison
use india-strategy-lab; for a chart read use india-technical-analyst.

## Rules for the answer

- NO_TRADE is a valid, often correct answer. Never push for a trade because
  the user wants one or wants a daily profit.
- Show both sides: the strategy prints reasons for and against.
- A backtest with fewer than 30 trades is INCONCLUSIVE: say so plainly. One
  stock rarely gives 30 trades; prefer the lab for evidence.
- Only call a strategy promising if BOTH the training and the later test
  period are positive after charges AND it beats the buy-and-hold baseline
  printed in the report; still recommend paper trading first.
- The single-stock backtest applies the same risk manager as paper trading,
  including the capital floor and circuit breaker, so trading may stop
  after losses: report that as protection working.
- At the default ₹200 budget almost every trade is blocked by charges.
  Explain this rather than loosening limits. `--capital` is a study budget,
  not a suggestion to trade that amount.
- This is research, not investment advice.
