---
name: india-strategy-lab
description: >-
  Test and compare trading strategies on real NSE data like a sceptical
  quant: a portfolio-level lab (many stocks, one cash account, Groww charges,
  next-open fills) against Nifty 50 and buy & hold, split into an earlier
  and a later out-of-sample half, plus single-stock backtests and day-by-day
  replays for any strategy. Use when the user asks "which strategy works",
  "test this strategy", "compare strategies", "is there an edge", "make a
  better strategy", or "backtest everything".
---

# india-strategy-lab

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" strategies
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" lab --universe large_caps_20 --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" lab --universe holdout_25 --data-dir data/real --strategies donchian_trend,trend_filtered_core
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" lab --data-dir data/real --start 2017-11-01 --split 2021-11-01 --capital 100000
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" lab --universe large_caps_20 --data-dir data/real --gate
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" backtest INFY --strategy donchian_trend --data-dir data/real --capital 20000 --risk 200
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" replay --strategy trend_template --data-dir data/real --start 2024-01-01 --capital 50000 --risk 500
```

Needs `data-fetch` stocks plus `data-fetch --indices --etf` (Nifty 50 for the
regime filter and benchmark, NIFTYBEES for the ETF strategy).

## Strategies (rules fixed BEFORE testing; textbook parameters)

Signal (per stock): `ma_trend_pullback`, `donchian_trend` (55-day breakout,
3-ATR trailing stop), `trend_template` (Minervini/VCP-style base breakout),
`rsi2_reversion` (Connors dip buy). Allocation (monthly): `momentum_rotation`,
`trend_filtered_core`, `etf_trend`.

## How to judge (say all of this)

- The verdict compares with **equal-weight buy & hold of the same stocks**
  after charges, in the LATER half and the full period. Beating zero is not
  enough; beating Nifty is not enough.
- Fewer than 30 trades = INCONCLUSIVE. A good earlier half with a bad later
  half = overfitting until proven otherwise.
- Re-run on the `holdout_25` universe before believing any result.
- Survivorship bias: the universes are today's large caps, which flatters
  every long-only line. Prices exclude dividends.
- Each extra strategy or parameter tried raises the odds of a lucky result.
  Do not tune parameters to the test period; if the user insists, label the
  result "fitted, not tested" and re-test on the holdout universe.
- Known result (docs/STRATEGY_LAB.md, 2016-2026 real data): no strategy beat
  buy & hold after charges; the trend filter cut max drawdown roughly in
  half to two-thirds at a cost of ~3-4% CAGR; swing strategies lost money
  after charges. Quote it when relevant; never promise profits.
- Use `--capital` only as a STUDY budget. Below ~₹25,000 charges dominate
  everything except a single ETF.
- Judge LOSS too, not only return: max drawdown, worst year, share of
  losing months (`worstYr%`, `lossMo%`). `--gate` adds each swing strategy
  with the Nifty 50 market gate; it lowered losses everywhere in testing,
  which is why it is on by default.
- For a second opinion on any result, use the `india-strategy-critic` agent.
