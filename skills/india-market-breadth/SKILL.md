---
name: india-market-breadth
description: >-
  Measure breadth and regime of the user's own NSE watchlist from local CSVs:
  % above SMA50/SMA200, SMA20>SMA50 share, advancers/decliners, 52-week highs
  and lows, and a RISK_ON / NEUTRAL / RISK_OFF label that can gate autopilot
  entries. Use when the user asks "how is the market", "is it risk-on",
  "market breadth", "regime", or "should the autopilot sit out".
---

# india-market-breadth

```bash
python -m india_trading.cli breadth [--data-dir data/real] [--as-of 2025-09-22]
```

- This is breadth of the CSVs in the data folder, NOT Nifty or NSE-wide
  breadth: no verified source for that is wired in. Say so every time.
- Fewer than 5 symbols: the output says the reading is noisy. Repeat that.
- `regime_gate: true` in `config/settings.yaml` makes the autopilot skip new
  entries while the regime is RISK_OFF (exits still run). It only ever
  removes trades; it never adds any.
- India VIX and official NSE advance/decline data are on the roadmap only
  after a verified source exists. Do not quote numbers for them.
