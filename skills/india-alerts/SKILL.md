---
name: india-alerts
description: >-
  Check price and setup alerts for NSE stocks (above/below a price, day
  change, RSI levels, new 52-week high/low, crossing a moving average) and
  automatic alerts for open paper positions near their stop or target,
  optionally on a schedule. Never places orders. Use when the user says
  "alert me when X crosses", "watch INFY for me", "set a price alert",
  "check my alerts", or "tell me if my stop is close".
---

# india-alerts

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" alerts --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" alerts --file config/alerts.yaml --data-dir data/real --prices INFY=1520.5 --price-source groww-mcp
```

Rules live in `config/alerts.yaml` in the project (copy
`${CLAUDE_PLUGIN_ROOT}/config/alerts.example.yaml`). Keys: `above`, `below`,
`change_below_pct`, `change_above_pct`, `rsi14_below`, `rsi14_above`,
`new_52w_high`, `new_52w_low`, `cross_above`/`cross_below` (sma20, sma50,
sma150, sma200), `note`. Add a rule for the user by editing that file.

## Scheduling (only if the user asks)

Use `/loop` (e.g. every 30 minutes, 09:15-15:30 IST, Mon-Fri) repeating:
read current prices with a read-only Groww tool → run `alerts --prices ...`
→ report only new triggers. Without live prices alerts use the last close,
so say "as of the last close". Claude and the computer must be running.

Alerts inform; they never buy or sell. Not advice.
