---
name: india-corporate-actions
description: >-
  Dividends and splits for NSE stocks from the fetched data (past ex-dates,
  trailing 12-month dividend and yield, dividend cuts), and how to handle
  results dates and announcements that the data feed does not include. Use
  when the user asks "dividend yield of X", "did X cut its dividend", "split
  history", "ex-dividend", "when are results", or "corporate actions".
---

# india-corporate-actions

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" actions --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" actions ITC COALINDIA TCS --data-dir data/real
```

`data-fetch` saves the events to `data/real/events/SYMBOL.json`.

## Rules

- The feed (Yahoo, unofficial) gives PAST ex-dates only. Upcoming ex-dates,
  record dates, bonus issues and quarterly results dates are not in it. For
  those, use the india-results-analyst / india-news-analyst agents (web
  search with sources) or the company's NSE announcements page, and say
  where each date came from.
- Yield = last 12 months' dividends / last close. A one-off special dividend
  inflates it; check the history before calling a stock "high yield".
- Prices are split-adjusted, not dividend-adjusted, so backtests exclude
  dividends.
- Holding through results is a gap risk for any stop. Not advice.
