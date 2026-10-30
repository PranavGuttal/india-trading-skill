---
name: india-trade-research
description: >-
  Analyse one NSE stock with the deterministic ma_trend_pullback strategy and
  backtest it with Indian (Groww) charges. Use when the user says "analyse
  SYMBOL", "should this setup work", "backtest", "how did this strategy do",
  or asks for entry/stop/target levels. Returns TRADE or NO_TRADE with reasons.
---

# india-trade-research

All indicator maths is done by Python (`src/india_trading/indicators`), never
in your head. Report the numbers the tool prints; do not invent any.

```bash
python -m india_trading.cli analyze SYMBOL [--data-dir data/real] [--as-of YYYY-MM-DD]
python -m india_trading.cli backtest SYMBOL [--capital 20000 --risk 200] [--out reports/trades.csv]
```

## Rules for the answer

- NO_TRADE is a valid, often correct answer. Never push for a trade because
  the user wants one or wants a daily profit.
- Show both sides: the strategy prints reasons for and against.
- A backtest with fewer than 30 trades is INCONCLUSIVE: say so plainly.
- Only call a strategy promising if BOTH the training and the later test
  period are positive after charges, and still recommend paper trading first.
- Compare with the buy-and-hold baseline printed in the report.
- At the default ₹200 budget almost every trade is blocked because Groww's
  ₹5 minimum brokerage and DP charges exceed the ₹10 risk limit. Explain this
  rather than loosening limits. Use `--capital` only to study the strategy,
  not as a suggestion to trade that amount.
- This is research, not investment advice.
