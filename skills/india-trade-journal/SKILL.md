---
name: india-trade-journal
description: >-
  Read, summarise and export the trade journal (signals, NO_TRADEs, risk
  blocks, approvals, simulated fills, exits, errors). Use when the user asks
  "show my journal", "what did I trade", "why did it block", "export trades",
  or wants a weekly review of their paper trading.
---

# india-trade-journal

```bash
python -m india_trading.cli journal --limit 50
python -m india_trading.cli journal --mode paper --export reports/journal.csv
python -m india_trading.cli paper status
```

## Review checklist

1. How many signals, how many blocked by risk, and the top block reasons.
2. Closed trades: net P&L after charges; charges as a share of gross P&L.
3. Did every executed order have an APPROVED event before ORDER_SUBMITTED?
4. Any ERROR or RECOVERY events? Explain each one.
5. Fewer than 30 closed trades = too early to judge the strategy.

The journal never stores passwords, PINs, OTPs, tokens or account numbers;
payload keys that look like secrets are redacted. Backtest, paper and live
records are kept separate by the `mode` column.
