---
name: india-allocation
description: >-
  Run the monthly allocation strategies in PAPER: an index ETF (NIFTYBEES)
  held only while Nifty 50 is above its 200-day average, the same rule on
  an equal-weight basket, or a top-5 momentum rotation. Shows today's target
  holdings and rebalances a separate paper account on the last trading day
  of the month. Use when the user asks for "a safer strategy", "protect my
  capital", "invest monthly", "ETF strategy", "trend filter", "momentum
  rotation", or "what should I hold this month".
---

# india-allocation

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" allocate
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" allocate --strategy-name trend_filtered_core --universe large_caps_20 --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" allocate --strategy-name momentum_rotation --universe large_caps_20 --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" allocate --paper
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" allocate --paper --force --prices NIFTYBEES=262.9 --price-source groww-mcp
```

Needs `data-fetch --indices --etf` (and stocks for the basket/rotation).

## Say this honestly

- Tested 2017-2026 on real data (docs/STRATEGY_LAB.md): the trend filter
  cut the worst fall from about -36% to -21% (ETF) and -34% to -12%
  (basket) but returned ~3-4% a year LESS than just holding. It is a
  capital-protection choice, not an edge, and it can whipsaw.
- Below ~₹25,000 only the single-ETF version is economical; the basket
  needs ~₹1 lakh because of per-order charges.
- `--paper` uses its own paper account (state/allocation/), auto-approved
  only because it is simulated. It checks the kill switch, the capital
  floor (sells everything and engages the kill switch if breached), cash
  incl. charges and the per-order cap. It never places real orders.
- Rebalancing happens on the last trading day of the month; `--force` only
  for testing. Real money: the user can follow the monthly signal in the
  Groww app themselves; this skill does not send orders.
- Cash earns nothing in the simulation. Not advice.
