# Risk policy

All checks live in `src/india_trading/risk/manager.py` and run in code, with
no language model in the loop. If any check cannot be evaluated, the order is
blocked (fail closed).

## Defaults
| Setting | Default |
|---|---|
| TRADING_MODE | paper |
| LIVE_TRADING_ENABLED | false |
| MAX_EXPERIMENTAL_ALLOCATION_INR (the budget) | 200 to start; change with `budget set N` |
| max_single_order_pct | 100% of the budget |
| MAX_OPEN_POSITIONS | 1 |
| risk_per_trade_pct (loss at stop incl. charges) | 1% of the budget |
| daily_loss_pct | 3% of the budget |
| weekly / monthly loss limit | 2× / 4× daily unless set |
| max_consecutive_losses → loss_cooldown_days | 3 → 2 business days |
| regime_gate (market gate) | index: no new entries while Nifty 50 ≤ its 200-day average or its data is missing/stale |
| capital_floor_pct | 90 (% of the budget that must survive; 0 = off) |
| max_trades_per_day | 2 |
| min_reward_risk | 1.5 |
| min_reward_to_cost | 2.0 |
| min_price_inr | 20 |
| ALLOW_SHORT_SELLING / DERIVATIVES / LEVERAGE | false (true is rejected at load) |
| REQUIRE_HUMAN_APPROVAL | true (cannot be false in live mode) |

## The budget scales everything
The budget is one number (`max_experimental_allocation_inr`). Every money
limit is a percentage of it, so investing more or less is one command:

```
python scripts/india.py budget              # limits + paper results
python scripts/india.py budget set 5000     # max order ₹5,000, risk ₹50/trade, daily ₹150, floor ₹4,500
```

`budget set` saves the amount in `config/settings.yaml` and adds or removes
the difference in paper cash, like a deposit or withdrawal. It refuses to
cut the budget below money already in open positions or lost. A fixed ₹
amount (`max_risk_per_trade_inr`, `max_single_order_value_inr`,
`daily_loss_limit_inr`) overrides its percentage and does NOT scale; leave
those blank unless you want that. Base changes on 30+ closed trades and net
results after charges (`review`), not on a few wins or losses.

## What ₹200 means in practice
The ₹200 is an **application-level** budget. Groww does not isolate it: the
same login can reach everything else in the account, and nothing in Groww
stops a manual order above ₹200.

With Groww's published schedule (copied 2026-10-30), a ₹200 delivery round
trip costs about ₹36 (₹35.85 by `risk/costs.py`): ₹5 minimum brokerage each
side, the DP charge on the sell, plus 18% GST. That is ~18% of the position.
Intraday avoids the DP charge but still costs about ₹12 (~6%). Because the per-trade risk limit
(1% = ₹2 at ₹200) **includes** charges, the risk manager blocks every ₹200 delivery trade
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
remaining daily/weekly/monthly allowance → capital floor → duplicate intent.
(The market gate check sits with the session check, before account checks.)

## Market gate
Default `regime_gate: index`. In the lab it reduced max drawdown, losing months and
charges for all four swing strategies on both universes and both halves of
2017-2026 (STRATEGY_LAB.md, "Loss reduction"). It blocks new entries only; exits
always run. Without fresh Nifty 50 data it blocks (fail closed).

## Capital floor
`capital_floor_pct` (default 90) is the share of the budget that must survive.
- **Before a trade:** it is allowed only if its loss at the stop, charges
  included, still leaves equity above the floor, with every open position
  valued at its own stop (paper broker and live ledger both report this
  `equity_at_stops`). With ₹10,000 and 90%, at most ₹1,000 is ever at risk.
- **After a breach:** if equity at current prices is found below the floor
  (a gap through a stop can do this), the paper autopilot and the allocation
  pilot sell everything and engage the kill switch. Only the user releases it.
- It limits losses; it cannot guarantee them, and nothing can guarantee a profit.

## Autopilot (paper only)
The autopilot approves paper entries automatically, but every entry still
goes through all checks above. `AutoPilot` refuses a live adapter in its
constructor. Exits follow the strategy's exit policy (stop raised by a trailing
stop where the strategy has one, target, close rules, max hold) and are not
blocked by entry limits or the kill switch, because they only reduce risk.
The allocation pilot (`allocate --paper`) uses its own paper account and its own
deterministic checks (kill switch, capital floor, cash incl. charges, order cap).

## Limits of these controls
They do **not** guarantee a loss can't exceed plan. Gaps through a stop,
slippage, partial fills, broker outages, charge changes, and manual actions
outside this app can all produce worse outcomes.

## Live (real money)
Locked by default. Unlocking requires all of:
- every live switch;
- graduation: at least 30 closed forward-paper trades on at least 20 distinct
  days, positive after charges, real data and live-read prices only. Each
  typed price must fall inside that day's real NSE low–high range (±0.5%),
  and the floors cannot be lowered in settings;
- the RiskManager, with cash read from Groww;
- an explicit per-order yes.

Then the order goes one of two ways:
- **Claude sends it:** only in Claude Code with the guard hook, within
  5 minutes, and only if the call exactly matches the ticket.
- **You place it in the Groww app** (`--send-via app`).

The live budget is the same `max_experimental_allocation_inr` (your budget;
₹200 until you change it). There is no unattended live trading. See GROWW_INTEGRATION.md.

What the price check does NOT catch: a price that was inside the day's range
but not the price at the moment you decided. The journal timestamps help you
audit that; it is on you to type what you actually saw.

## Kill switch
`python scripts/india.py kill-switch on` creates `state/KILL_SWITCH`.
While it exists, every new order is blocked and the monitor stops. It
survives restarts.
