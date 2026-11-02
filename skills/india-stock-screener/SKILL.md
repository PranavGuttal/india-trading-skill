---
name: india-stock-screener
description: >-
  Screen a universe of NSE stocks for setups: each strategy's signal
  (pullback, 55-day breakout, Minervini trend template / VCP-style base
  breakout, RSI(2) dip), near 52-week highs, momentum bursts, gap-ups on
  volume, with a 1-99 RS rating, trend stage, ATR% and liquidity. Use when
  the user asks "find stocks", "scan the market", "breakout stocks", "VCP",
  "CANSLIM", "momentum stocks", "strongest stocks", "what's setting up".
---

# india-stock-screener

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" universe-fetch NIFTY500
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" data-fetch --universe NIFTY500
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" screen --universe NIFTY500 --data-dir data/real --min-rs 80 --top 25
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" screen --data-dir data/real
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" screen --universe large_caps_20 --data-dir data/real --min-rs 70
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" screen --data-dir data/real --setup donchian_trend
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" screen --data-dir data/real --setup near_high --top 10
```

Setups: `ma_trend_pullback`, `donchian_trend`, `trend_template`,
`rsi2_reversion`, `trend_template_only`, `near_high`, `momentum_burst`,
`gap_up_volume`, `oversold_uptrend`.

## Rules

- Only stocks with data in the folder are screened. For the full Nifty 500:
  `universe-fetch NIFTY500` (official NSE list) then `data-fetch --universe
  NIFTY500` (~10 minutes the first time). Never claim to have scanned "all
  of NSE". Sectors are NSE's official industries once lists are downloaded.
- Series BE/RR stocks in the list trade under surveillance/special rules;
  say so if one shows up.
- RS is a rank INSIDE this universe, not IBD's market-wide rating.
- Technical data only: no earnings growth, so this is CANSLIM's chart half.
  For results/news on a candidate use india-news-research.
- `gap_up_volume` often means news: check it before acting.
- A setup is a lead to research with `technical` and `plan`, not a buy
  signal. The strategy lab found no setup that beat buy & hold after
  charges; say so if asked how reliable they are. Not advice.
