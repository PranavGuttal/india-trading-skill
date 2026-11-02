---
name: india-technical-analyst
description: >-
  Produce a technical read of one NSE stock from its daily bars: trend stage
  and moving averages, 52-week position, swing support and resistance,
  RSI/MACD/ATR, volume, relative strength vs Nifty 50 and its sector index,
  recent dividends/splits, and what every strategy says today. Use when the
  user asks "analyse the chart of X", "technical view on X", "support and
  resistance for X", "is X in an uptrend", or "how is X doing vs Nifty".
---

# india-technical-analyst

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" technical INFY --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" technical INFY --data-dir data/real --as-of 2025-03-28
```

If the symbol has no file, fetch it first: `data-fetch INFY` (and
`data-fetch --indices` for the Nifty/sector comparison).

## How to present it

- Quote the numbers printed; never compute indicators yourself or read
  levels off memory. Give the as-of date and the data source.
- Lead with the trend (stage, price vs 50/200-day), then levels, then
  momentum and relative strength, then the strategies' verdicts.
- Support/resistance are clustered swing points from the last ~120 bars:
  zones, not exact prices.
- Mention corporate actions in the window (splits change old prices;
  dividends are not adjusted).
- No earnings or valuation here; offer india-news-research for results.
- Finish with what would change the picture (e.g. "a close below the
  200-day average at ₹X"). Not advice; no price predictions.
