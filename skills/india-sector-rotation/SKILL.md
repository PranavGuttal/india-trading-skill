---
name: india-sector-rotation
description: >-
  Rank NSE sector indices (Nifty Bank, IT, Pharma, Auto, FMCG, Metal,
  Energy, Realty, PSU Bank, Infra, Fin Services, PSE, Consumption) by
  relative strength against Nifty 50 over 1, 3 and 6 months and by trend,
  and name leaders and laggards. Use when the user asks "which sectors are
  strong", "sector rotation", "where is money flowing", "best sector now",
  "is IT/pharma/banking doing well", or wants stock ideas from leading sectors.
---

# india-sector-rotation

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" sectors
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" sectors --as-of 2024-06-28
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" screen --universe large_caps_20 --data-dir data/real
```

Needs `data-fetch --indices`.

- RS columns are percentage points versus Nifty 50; the score weights
  1m/3m/6m as 0.2/0.4/0.4. Leaders must also be in an uptrend (above both
  the 50- and 200-day averages).
- Stocks map to sectors through `config/sectors.yaml` (approximate,
  editable). The screener prints each stock's sector, so you can look for
  setups inside leading sectors.
- Relative strength is a description of the past, not a forecast. Sector
  momentum reverses; say so. Not advice.
