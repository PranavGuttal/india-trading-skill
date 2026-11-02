---
name: india-market-breadth
description: >-
  Measure breadth of the user's own NSE watchlist or data folder from local
  CSVs: % above SMA50/SMA200, SMA20>SMA50 share, advancers/decliners,
  52-week highs and lows, and a RISK_ON / NEUTRAL / RISK_OFF label that can
  gate autopilot entries. Use when the user asks for "breadth of my
  watchlist" or "should the autopilot sit out"; for the Nifty-based market
  regime use india-market-regime instead.
---

# india-market-breadth

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" breadth --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" breadth --data-dir data/real --as-of 2025-09-22
```

- This is breadth of the CSVs in the folder, NOT NSE-wide breadth. For the
  market itself (Nifty 50 trend, distribution days, India VIX) run
  `regime` (india-market-regime) and say which one you used.
- Fewer than 5 symbols: the output says the reading is noisy. Repeat that.
- `regime_gate: watchlist` in `config/settings.yaml` makes the autopilot skip
  new entries while this breadth is RISK_OFF (exits still run). The default
  `index` gate uses the Nifty 50 trend instead, which was tested. It only ever
  removes trades; it never adds any.
