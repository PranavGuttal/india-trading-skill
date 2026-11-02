---
name: india-market-monitor
description: >-
  Check the NSE session and scan a watchlist of NSE cash-equity CSVs for the
  ma_trend_pullback setup, read-only. Use when the user asks "is the market
  open", "scan my watchlist", "market check", "what's setting up today", or
  wants to read their Groww holdings/positions/charts through the Groww
  connector. Never places orders.
---

# india-market-monitor

Read-only. Nothing in this skill can place, modify or cancel an order.

## Commands (run in the user's project folder)

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" market-check        # NSE session, holiday-list status
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" scan                # strategy on every CSV in data_dir
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" monitor start --interval 300 --ticks 1   # one read-only tick
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" monitor stop
```

## Using the Groww connector (if the user has enabled it)

1. First LIST the Groww tools that are actually available in this chat. Do
   not guess tool names or parameters; read each tool's schema.
2. Use only read-only tools: holdings, positions, quotes, chart/candle data.
3. Do NOT call any tool that places, modifies or cancels an order, even if
   asked. Order placement in this project is always done by the user in the
   Groww app from a printed ticket.
4. When a quote is used, report its source and timestamp. If the tool gives
   no timestamp, say the price's time is unknown and treat it as not live.
5. To analyse Groww candle data, save it as `data/real/<SYMBOL>.csv` with
   columns `date,open,high,low,close,volume,source` (source=groww-mcp) and run
   `scan --data-dir data/real`.

## Reporting

- Always say which data source and as-of date each result uses.
- Data in `data/sample/` is SYNTHETIC. Say so whenever it is used.
- If the holiday list is not verified for the year, say that weekday
  holidays are not detected.
