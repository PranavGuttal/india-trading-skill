---
name: india-stock-analysis
description: >-
  Full one-stock view for an NSE company: technical picture (trend, levels,
  relative strength vs Nifty and its NSE industry index), fundamentals from
  its latest results filing with sources, dividends/splits, recent news and
  circulars, institutional flows if relevant, the market gate, what each
  strategy says, and a risk-sized plan only if one fires. Use when the user
  asks "analyse X completely", "fundamental and technical view of X",
  "should I look at X", or "tell me everything about X".
---

# india-stock-analysis

Run in this order; quote only what the tools and agents return.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-fetch INFY
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" technical INFY --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" actions INFY --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" regime --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" plan INFY --data-dir data/real --risk 500 --budget 20000
```

Then delegate (india-news-research):
- `india-results-analyst`: latest quarter vs year ago and last quarter.
- `india-news-analyst`: last 30 days of news and exchange announcements.
- `india-flows-analyst`: only if the user asks about institutional buying.

## Write it up as

1. **Business snapshot** (from the results agent, with sources): revenue,
   profit, margin trend, one-offs. "Not stated" where the filing lacks it.
2. **Technical picture**: stage, trend vs 50/200-day, support/resistance,
   relative strength vs Nifty and its NSE industry (official classification
   when `universe-fetch` lists are downloaded).
3. **Events**: dividends/splits, upcoming results or record dates (sourced).
4. **Market backdrop**: market gate open/closed, sector rank.
5. **What the rules say**: each strategy's verdict; a plan only if one says
   TRADE and the gate is open (with loss at stop incl. charges).
6. **What would change the view**, in levels and dates.

Rules: no price targets or predictions; facts sourced and dated; mark
anything inferred. The lab found no strategy that beat buy & hold after
charges, so a positive write-up is a reason to research further, not to buy.
Not advice.
