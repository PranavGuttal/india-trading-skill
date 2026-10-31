---
name: india-trade-review
description: >-
  Review paper-trading performance and decide whether the strategy is earning
  its keep: win rate, expectancy, charges as a share of gross, worst losing
  streak, exit reasons, risk-block reasons, and journal integrity, with the
  30-trade evidence rule. Use when the user asks "how am I doing", "weekly
  review", "is it working", "should I go live", or "postmortem".
---

# india-trade-review

```bash
python -m india_trading.cli review                    # real paper account (state/paper.db)
python -m india_trading.cli replay ...                # what the autopilot would have done historically
python -m india_trading.cli backtest SYMBOL ...       # strategy-only check with train/test split
python -m india_trading.cli journal --limit 50
```

## How to review

1. Numbers first, from the tools. Then one short paragraph on what they mean.
2. Under 30 closed trades: "too early", whatever the P&L.
3. Charges share of gross above ~0.5 means costs, not the market, decide
   results: say that the trade size is too small for the charges.
4. Any order without an APPROVED event, any ERROR or RECOVERY: explain each.
5. For a second opinion, hand the numbers to the `india-strategy-critic`
   agent if it is installed.

## "Should I go live?"

There is no live order path in this project. Before even considering one,
all must hold: weeks of paper trading on REAL data, ≥30 closed trades,
positive after charges in both the paper review and the backtest's
out-of-sample period, and the Groww connector's tools inspected and
documented. If any is missing, the answer is no, and say which.
