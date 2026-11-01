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

- The circuit breaker (weekly/monthly loss limits, losing-streak cooldown)
  applies in the backtest exactly as in paper trading.

## Replay (autopilot day by day)
```bash
python -m india_trading.cli replay [--start 2024-01-01 --end 2025-06-30] [--capital 20000 --risk 200] [--symbols A,B]
```
Runs the paper autopilot once per trading day at 15:20 IST with that day's
close as the price, over all watchlist symbols together (so max positions,
daily limits and cooldowns interact as they would live). Entries fill near
the close; exits see the full day's bar (gap/stop/target/SMA50/max hold).
State goes to `state/replay/` and is replaced on each run. SYNTHETIC sample,
₹20,000 study budget: 750 days, 150 signals, 54 trades, net ₹-2,370.95 after
₹2,276.44 charges → NO EDGE SHOWN. At ₹200: 291 signals, all blocked.

## Time machine
`timemachine SYMBOL [--entry --stop --target]` bootstraps the stock's last
250 daily bars into 10,000 paths of up to 10 days; stop is checked before
target; charges for the quantity are deducted. It answers "how often does
this plan hit target vs stop", not "will it work".

Not modelled yet: partial fills, circuit limits/price bands, corporate
actions (use adjusted data), liquidity limits, holidays without a verified list.

## First REAL-data result (2026-11-01)
Data: `data-fetch` (Yahoo Finance, unofficial), 20 large NSE stocks
(RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN, ITC, LT, BHARTIARTL,
HINDUNILVR, AXISBANK, KOTAKBANK, MARUTI, SUNPHARMA, TITAN, BAJFINANCE,
ASIANPAINT, HCLTECH, WIPRO, NTPC), 1,236 daily bars each, 2021-11-01 → 2026-10-30.
`ma_trend_pullback` v1.0.0, study budget ₹20,000 per stock, ₹200 risk/trade:

| | Value |
|---|---|
| Trades / wins | 760 / 243 (32%) |
| Net after charges | **₹-37,002** (charges ₹33,485; gross ≈ ₹-3,517) |
| Train period / test period (last 30%) | ₹-25,064 / ₹-11,939 (209 trades) |
| Stocks with positive net | **0 of 20** |
| Buy & hold, same capital, summed | ₹+1,63,782 |

Verdict: **NO EDGE.** Before charges the strategy is roughly break-even;
Groww charges turn that into a steady loss, in both periods, on every stock.
It must not be used with real money. Graduation will not pass with it.

## Example output — SYNTHETIC data (not real prices)

Default ₹200 budget:
```
BACKTEST SYNTH_TREND | strategy ma_trend_pullback | data csv:SYNTH_TREND.csv (SYNTHETIC)
Signals 79 | blocked by risk/charges 79 | trades 0
Top block reasons: no whole-share quantity fits the budget, order cap and per-t ×79
VERDICT: INCONCLUSIVE: only 0 trades (< 30). Do not treat this as evidence of an edge.
```

Study budget ₹20,000, ₹200 risk/trade (with the losing-streak cooldown):
```
Signals 27 | blocked by risk/charges 8 | trades 19
Net P&L ₹-1885.88 (gross ₹-1067.54, charges ₹818.34) | win rate 0.053 | PF 0.13
Train (< 2025-01-06): trades 12 net ₹-1302.51 | Test (>= 2025-01-06): trades 7 net ₹-583.37
Baseline buy & hold (same capital, after charges): ₹-11799.64
Top block reasons: N losses in a row: cooling off for N business days after N ×8
VERDICT: INCONCLUSIVE: only 19 trades (< 30).
```
These numbers say nothing about real markets; they show the engine runs,
charges are applied, and verdicts are conservative. Run it on real adjusted
NSE data before drawing any conclusion.
