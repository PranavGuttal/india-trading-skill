# Strategy lab — real NSE results (2026-11-01)

```bash
python scripts/india.py data-fetch --universe large_caps_20 --indices --etf
python scripts/india.py data-fetch --universe holdout_25
python scripts/india.py lab --universe large_caps_20 --data-dir data/real --start 2017-11-01 --split 2021-11-01
python scripts/india.py lab --universe holdout_25   --data-dir data/real --start 2017-11-01 --split 2021-11-01
```

## Protocol (fixed before looking at results)

- **Data:** Yahoo Finance daily bars (unofficial), 2016-11-01 → 2026-10-30.
  The first year is indicator warm-up, so trading runs 2017-11-01 → 2026-10-30.
  Prices are split-adjusted and exclude dividends. Two bad-tick days in the
  ETFs (2019-12-19/20, prices at 1/10th) were removed by `data-fetch`.
- **Universes:**
  - `large_caps_20`: the development set;
  - `holdout_25`: 25 different large caps, used only to check results.
  Both are today's large caps, so **survivorship bias flatters every long-only line**.
- **Periods:**
  - earlier (2017-11 → 2021-10): development;
  - later (2021-11 → 2026-10): out-of-sample.
- **Account and costs:**
  - ₹1,00,000 study capital, one cash account across all stocks, max 5 positions, 1% of equity risked per signal trade;
  - Groww delivery charges on every order, plus 10 bps slippage;
  - decisions on the close, fills at the next open; stop checked before target inside a bar.
- **Parameters:** textbook values (Turtle 55/20 days, Minervini template,
  Connors RSI(2) < 10, 200-day trend filter, 6/12-month momentum). Not tuned to NSE.
- **Verdicts:** each strategy is judged against buy & hold of the same
  instruments after charges, in the later half and over the full period.
  `etf_trend` is judged against holding NIFTYBEES.

## Results, full period 2017-11 → 2026-10 (CAGR % / max drawdown %)

| | large_caps_20 | holdout_25 | Verdict (both) |
|---|---|---|---|
| Nifty 50 index (no costs) | 9.2 / −38.4 | 9.2 / −38.4 | benchmark |
| NIFTYBEES buy & hold | 10.4 / −36.4 | 10.4 / −36.4 | benchmark |
| Equal-weight buy & hold | **11.7 / −34.0** | **13.1 / −29.2** | benchmark |
| ma_trend_pullback | −15.2 / −77.3 | −13.8 / −75.3 | NO EDGE |
| donchian_trend | −1.7 / −30.5 | −5.2 / −41.3 | NO EDGE |
| trend_template | −1.3 / −17.9 | −0.5 / −26.5 | NO EDGE |
| rsi2_reversion | −14.4 / −75.2 | −13.7 / −73.5 | NO EDGE |
| momentum_rotation | 6.0 / −21.8 | 7.6 / −24.9 | NO EDGE |
| trend_filtered_core | 8.2 / **−12.0** | 7.3 / −25.3 | SAFER, LOWER RETURN |
| etf_trend | 6.6 / −20.9 | 6.6 / −20.9 | NO EDGE (worse than NIFTYBEES in 2021-26) |

**Later half only (2021-11 → 2026-10)**, large_caps_20 / holdout_25:
- equal-weight buy & hold: 6.4 and 8.6 %/yr;
- trend_filtered_core: 3.1 and 4.8;
- momentum_rotation: 5.2 and 4.7;
- every swing strategy was negative.

**Charges paid over the full period:**
- ma_trend_pullback ₹82,606, rsi2_reversion ₹70,950, donchian_trend ₹29,372;
- buy & hold ₹1,232.

The swing strategies are close to break-even before charges. Groww's ~0.25–0.5% round-trip delivery cost per trade turns them into steady losers.

## What this means

1. **No strategy here beat buying and holding after charges**, on either
   universe, in either half. That includes the strategies adapted from both
   reference repos (VCP/trend template, breakouts, pullbacks, oversold
   bounces, momentum rotation).
2. **The trend filter is a risk control, not an edge.** It means holding
   only while Nifty 50 closes above its 200-day average at month end.
   - On the 20-stock basket it cut the worst fall from −34% to −12%, at about 3.5% a year less return.
   - On the holdout basket it reduced the drawdown only a little (−29% to −25%) and lost about 6% a year of return.
   - On the ETF it cut the drawdown from −36% to −21%, but whipsawed in the calm 2021-26 period.
3. **Capital decides what is possible** (full period, `etf_trend` / `trend_filtered_core` CAGR):

   | Capital | ETF hold | ETF trend | Basket trend |
   |---|---|---|---|
   | ₹1,000 | 10.1% | 2.0% | not investable |
   | ₹10,000 | 10.4% | 6.1% | 0.2% |
   | ₹25,000 | 10.4% | 6.4% | 5.1% |
   | ₹1,00,000 | 10.4% | 6.6% | 8.2% |
   | ₹5,00,000 | 10.5% | 6.7% | 9.2% |

   Below about ₹25,000, per-order minimums and DP charges make anything but a single ETF uneconomic.
4. **The engine is honest, and the results look plausible:**
   - buy & hold beats the price index by ~1-2%/yr because NIFTYBEES reinvests dividends;
   - the 2020 crash shows in every drawdown;
   - the porting of the original strategy reproduces the earlier result exactly (760 trades, ₹-37,002.36).

## Loss reduction: the market gate (2026-11-02)

**Hypothesis (stated before running):** no new swing entries while Nifty 50
closes at or below its 200-day average. Open positions keep their own exits.
It was tested on the same two universes and periods, with the same costs
(`lab --gate`).

| Universe / period | Strategy | max DD free → gated | losing months free → gated | CAGR free → gated |
|---|---|---|---|---|
| large_caps_20, later | ma_trend_pullback | −60.2 → −54.1 | 70.0 → 56.7 | −16.7 → −14.4 |
| | donchian_trend | −25.1 → −22.1 | 61.7 → 55.0 | −5.3 → −4.8 |
| | trend_template | −14.1 → −13.4 | 53.3 → 48.3 | −2.2 → −1.8 |
| | rsi2_reversion | −58.8 → −50.7 | 76.7 → 60.0 | −16.2 → −13.1 |
| holdout_25, later | ma_trend_pullback | −62.3 → −61.0 | 73.3 → 65.0 | −17.3 → −17.0 |
| | donchian_trend | −39.3 → −36.1 | 66.7 → 56.7 | −9.2 → −8.6 |
| | trend_template | −24.9 → −16.7 | 71.7 → 56.7 | −5.4 → −3.5 |
| | rsi2_reversion | −54.5 → −41.0 | 68.3 → 51.7 | −14.5 → −9.7 |
| holdout_25, full | trend_template | −26.5 → −19.1 | 59.3 → 51.9 | −0.5 → **+0.5** |

**Results:**
- In all 16 strategy × universe × period cells, the gate lowered max
  drawdown, the share of losing months, and the charges paid.
- CAGR improved in 14 of 16 cells, by at most +4.8 points. The two
  exceptions were donchian_trend over the full period (−1.7 → −2.1 and
  −5.2 → −5.3).
- The single worst calendar year got worse in 4 cells:
  - donchian_trend on large_caps_20, both periods;
  - ma_trend_pullback on holdout_25, both periods (−23 → −30).

  Fewer trades means one bad year weighs more.
- It is a loss reducer, not an edge: the gated strategies still did not
  beat buy & hold.

**Third check: the official Nifty 500 list** (499 of 501 stocks with
Yahoo data; `universe-fetch NIFTY500` then `data-fetch --universe NIFTY500`).
This is a much larger, independent universe. It is today's list, so
survivorship bias is strong.

| Nifty 500, later 2021-11 → 2026-10 | CAGR % | max DD % | worst year % | losing months % | charges ₹ |
|---|---|---|---|---|---|
| Equal-weight buy & hold | **14.6** | −16.0 | +0.7 | 35.0 | 5,553 |
| trend_template / +gate | 2.6 / **4.8** | −25.8 / **−13.2** | −14.3 / −7.5 | 45.0 / 35.0 | 22,493 / 15,728 |
| donchian_trend / +gate | −1.3 / 2.6 | −41.7 / −32.6 | −15.7 / −14.1 | 51.7 / 43.3 | 24,703 / 20,370 |
| ma_trend_pullback / +gate | −12.5 / −10.7 | −53.0 / −48.1 | −31.0 / −21.6 | 58.3 / 51.7 | 79,362 / 57,867 |
| rsi2_reversion / +gate | −12.7 / −8.9 | −49.3 / −37.5 | −23.0 / −15.0 | 65.0 / 55.0 | 82,946 / 63,474 |

**Full period 2017-11 → 2026-10:**
- The gate improved CAGR and losing months for all four strategies.
- It lowered max drawdown for three of them. The exception is
  donchian_trend (−38.8 → −40.8).
- Buy & hold: 11.2 %/yr, −20.7 max DD.

**Conclusion (unchanged, now on three universes):**
- The gate reduces losses.
- trend_template is the least-bad swing strategy.
- Nothing beats holding.

**Adopted:**
- `regime_gate: index` is now the default, enforced in the risk manager for
  paper, autopilot, replay, backtest and the live desk.
- `trend_template` is the default swing strategy. It was the least-losing
  strategy in every cell. That ranking is consistent across both universes,
  but it was still chosen after seeing the data.

## Rules for using these results

- Do not tune parameters to these periods, then quote the result. Any new
  idea gets the same protocol: the development universe first, then the
  holdout universe and the later half.
- Paper-trade any strategy before real money. The live desk's graduation
  test still applies to signal strategies.
- Survivorship bias, no dividends in stock prices and no impact cost all
  make backtests look *better* than reality.
