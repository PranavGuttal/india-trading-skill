# Risk policy

All checks live in `src/india_trading/risk/manager.py` and run in code, with
no language model in the loop. If any check cannot be evaluated, the order is
blocked (fail closed).

## Defaults
| Setting | Default |
|---|---|
| TRADING_MODE | paper |
| LIVE_TRADING_ENABLED | false |
| MAX_EXPERIMENTAL_ALLOCATION_INR | 200 |
| MAX_SINGLE_ORDER_VALUE_INR | 200 |
| MAX_OPEN_POSITIONS | 1 |
| max_risk_per_trade_inr (incl. charges) | 10 |
| daily_loss_limit_inr | 20 |
| weekly / monthly loss limit | 2× / 4× daily (₹40 / ₹80) unless set |
| max_consecutive_losses → loss_cooldown_days | 3 → 2 business days |
| regime_gate (autopilot only) | false |
| max_trades_per_day | 2 |
| min_reward_risk | 1.5 |
| min_reward_to_cost | 2.0 |
| min_price_inr | 20 |
| ALLOW_SHORT_SELLING / DERIVATIVES / LEVERAGE | false (true is rejected at load) |
| REQUIRE_HUMAN_APPROVAL | true (cannot be false in live mode) |

## What ₹200 means in practice
The ₹200 is an **application-level** budget. Groww does not isolate it: the
same login can reach everything else in the account, and nothing in Groww
stops a manual order above ₹200.

With Groww's published schedule (copied 2026-10-30), a ₹200 delivery round
trip costs about ₹36 (₹35.85 by `risk/costs.py`): ₹5 minimum brokerage each
side, the DP charge on the sell, plus 18% GST. That is ~18% of the position.
Intraday avoids the DP charge but still costs about ₹12 (~6%). Because the per-trade risk limit
(₹10) **includes** charges, the risk manager blocks every ₹200 delivery trade
the strategy proposes. On the synthetic sample data, 100% of signals were
blocked at ₹200 (see BACKTESTING.md). This is intended: those trades lose
money to charges before price moves.

Options, if you want trades to pass, are a deliberate choice for you to make,
not a recommendation: keep paper trading at a larger *paper* budget to study
the strategy, or accept that real trading at ₹200 is mostly paying charges.

## Checks (in order)
kill switch → NO_TRADE → quote present/symbol match → delayed/stale/future
quote → penny floor → >2% price drift → price at/below stop → session open →
account verified → already holding → max positions (incl. pending) → max
trades/day → daily loss limit → weekly loss limit → monthly loss limit →
losing-streak cooldown → cost-aware qty (budget, order cap, risk incl.
charges, cash) → reward:risk → reward vs 2× charges → net reward > 0 →
remaining daily/weekly/monthly allowance → duplicate intent.

## Autopilot (paper only)
The autopilot approves paper entries automatically, but every entry still
goes through all checks above. `AutoPilot` refuses a live adapter in its
constructor. Exits (stop, target, close < SMA50, max hold) are not blocked by
entry limits or the kill switch, because they only reduce risk.

## Limits of these controls
They do **not** guarantee a loss can't exceed plan. Gaps through a stop,
slippage, partial fills, broker outages, charge changes, and manual actions
outside this app can all produce worse outcomes.

## Live (real money)
Locked by default. Unlock requires all live switches, graduation (≥30 closed
forward-paper trades on ≥20 distinct days, positive after charges, real data
and live-read prices only; floors cannot be lowered in settings), the
RiskManager with cash read from Groww, an explicit per-order yes (5-minute
expiry), and the guard hook match. The live budget is the same
`max_experimental_allocation_inr` (₹200 by default). See GROWW_INTEGRATION.md.

## Kill switch
`python -m india_trading.cli kill-switch on` creates `state/KILL_SWITCH`.
While it exists, every new order is blocked and the monitor stops. It
survives restarts.
