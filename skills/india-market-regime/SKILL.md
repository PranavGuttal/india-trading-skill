---
name: india-market-regime
description: >-
  Read the Indian market's regime from real index data: Nifty 50 vs its
  50/200-day averages (the tested trend filter), distribution days,
  follow-through days, India VIX and its percentile, universe breadth, and
  an exposure posture (how much of the budget it makes sense to have at
  risk). Use when the user asks "how is the market", "is it safe to buy
  now", "risk on or off", "should I be invested", "market top", "Nifty
  trend", "India VIX", or before any new entries.
---

# india-market-regime

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" regime --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" regime --universe large_caps_20 --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" regime --as-of 2020-03-23 --data-dir data/real
```

Needs `data-fetch --indices` (Nifty 50, India VIX, sectors).

## Reading it

- **Trend filter** (Nifty above/below its 200-day average) is the only part
  with a backtest behind it: holding only while it is ON roughly halved
  drawdowns in 2017-2026 but lowered returns. Lead with it.
- **Exposure posture** (0-100%) combines the trend, distribution days, VIX
  percentile, breadth and follow-through days with fixed weights. It is a
  HEURISTIC summary; say "heuristic" every time you quote it.
- Distribution days count only when the index volume is present; Yahoo's
  index volume has gaps. A follow-through day is a possible start, not a
  confirmed uptrend.
- Data is Yahoo Finance end-of-day (unofficial). Say the as-of date.
- The **market gate** (default `regime_gate: index`) uses exactly this trend
  filter inside the risk manager: no new swing entries anywhere (paper,
  autopilot, backtest, live desk) while Nifty 50 is below its 200-day average
  or its data is stale. Tested to lower losses; it never adds trades.
- This describes the present; it does not forecast. Not advice.
