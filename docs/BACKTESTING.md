# Backtesting

```bash
python -m india_trading.cli backtest SYMBOL [--capital 20000 --risk 200] [--out reports/trades.csv]
```

## Method
- Decision on the close of bar *t* using rows 0..t only; fill at bar *t+1*
  open plus slippage (`slippage_bps`, default 10 bps).
- The **same** `RiskManager` used for paper trading approves or blocks each
  signal, so charges, budget, risk-per-trade and reward-to-cost apply.
- Charges per trade from `risk/costs.py` (Groww schedule).
- Inside a bar, the stop is checked before the target (conservative). A gap
  below the stop exits at the open, not at the stop.
- Exits: stop, target, close < SMA50 (exit next open), max hold days.
- Chronological 70/30 train/test split; never shuffled.
- Baseline: buy & hold with the same capital, after one round trip of charges.
- Verdict: fewer than 30 trades → INCONCLUSIVE; full or test period ≤ 0 → NO EDGE SHOWN.

Not modelled yet: partial fills, circuit limits/price bands, corporate
actions (use adjusted data), liquidity limits, holidays without a verified list.

## Example output — SYNTHETIC data (not real prices)

Default ₹200 budget:
```
BACKTEST SYNTH_TREND | strategy ma_trend_pullback | data csv:SYNTH_TREND.csv (SYNTHETIC)
Signals 79 | blocked by risk/charges 79 | trades 0
Top block reasons: no whole-share quantity fits the budget, order cap and per-t ×79
VERDICT: INCONCLUSIVE: only 0 trades (< 30). Do not treat this as evidence of an edge.
```

Study budget ₹20,000, ₹200 risk/trade:
```
Signals 20 | blocked by risk/charges 0 | trades 20
Net P&L ₹-1324.99 (gross ₹-459.03, charges ₹865.96) | win rate 0.2 | PF 0.4
Train (< 2025-01-06): trades 13 net ₹-722.97 | Test (>= 2025-01-06): trades 7 net ₹-602.02
Baseline buy & hold (same capital, after charges): ₹-11799.64
VERDICT: INCONCLUSIVE: only 20 trades (< 30).
```
These numbers say nothing about real markets; they show the engine runs,
charges are applied, and verdicts are conservative. Run it on real adjusted
NSE data before drawing any conclusion.
