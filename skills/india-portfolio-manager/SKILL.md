---
name: india-portfolio-manager
description: >-
  Review the user's NSE holdings (from the Groww connector read-only, a CSV
  or JSON export, or the paper account): value, P&L, weights, sector
  concentration, volatility, correlation, and review triggers (below the
  200-day average, far from the 52-week high, oversized position or sector,
  dividend cut, deep loss). Never sells. Use when the user asks "review my
  portfolio", "my holdings", "am I diversified", "what should I look at in
  my Groww account", or "portfolio risk".
---

# india-portfolio-manager

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" portfolio
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" portfolio --holdings holdings.csv --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" portfolio --holdings holdings.json --data-dir data/real --prices INFY=1520.5,TCS=3901 --price-source groww-mcp
```

## Getting holdings from Groww (read-only)

1. List the Groww connector's tools; use only a read-only holdings tool.
   Never call an order tool here.
2. Save the rows to `holdings.json` (a list of objects with symbol, quantity
   and average price; common field names are recognised) in the project.
3. Fetch prices for missing symbols with `data-fetch`, then run `portfolio`.

## Reporting

- Triggers T1-T6 mean "review this", never "sell". Explain each one that
  fires; let the user decide.
- Sectors come from `config/sectors.yaml` (approximate); "Unclassified"
  means the map lacks the symbol.
- High average correlation means fewer real bets than the stock count.
- Say where prices came from (last close in data vs Groww read now).
- Do not store holdings anywhere except the user's own project folder.
  Not advice.
