# Architecture

```
            ┌─────────────── Claude skills (skills/india-*) ───────────────┐
            │  instructions + CLI entry points; Groww connector READ-ONLY   │
            └───────────────────────────────┬──────────────────────────────┘
                                            │ python scripts/india.py …   
┌───────────────────────────────────────────▼───────────────────────────────┐
│ Supervisor (workflows/supervisor.py)  — state machine, halts on failure     │
│ LOAD → VALIDATE → ANALYZE → RISK → TICKET → APPROVAL → EXECUTE → DONE       │
└──┬──────────────┬───────────────┬──────────────┬──────────────┬────────────┘
   │              │               │              │              │
Market data   Indicators +     Risk manager   Execution      Journal
csv_source    Strategy         (deterministic agent           (SQLite events,
calendar      ma_trend         + costs.py)    executor.py    CSV export,
(IST, NSE)    (TRADE/NO_TRADE)  fails closed  ─────────────   redaction)
                                              │ BrokerAdapter│
                                              ├ PaperBroker  (SQLite, idempotent)
                                              └ GrowwAdapter (raises Unsupported)
Monitor (monitoring/monitor.py): read-only polling, heartbeat, stop file, kill switch.
AutoPilot (workflows/autopilot.py): exits, optional regime gate, then Supervisor
  entries with automatic PAPER approval; refuses live adapters.
Replay (simulation/replay.py): AutoPilot once per past day, separate state dir.
Time machine (simulation/timemachine.py): Monte-Carlo odds of one plan.
Breadth (analysis/breadth.py) and Review (journal/review.py): pure reporting.
Backtester (backtesting/engine.py): same strategy + same RiskManager, next-bar fills.
Strategies (strategies/): declarative Strategy = named entry conditions + levels +
  ExitPolicy (take profit, ATR trail, close rules, max hold); one definition used by
  scan, analyze, backtest, lab, replay, autopilot and the live desk.
Portfolio lab (backtesting/portfolio.py, lab.py): many stocks, one cash account,
  max positions, benchmarks (Nifty, buy & hold, NIFTYBEES), earlier/later halves.
Analysis (analysis/): regime (Nifty, VIX, distribution/FTD), sectors, screener,
  technical, planner (size/plan/exit-plan), portfolio review, alerts, actions.
Allocation pilot (workflows/allocation.py): monthly ETF/basket/rotation, own paper account.
Launcher (scripts/india.py): finds a Python with the packages (per-user venv outside
  the plugin), runs the CLI in the user's project folder; `--guard` for the hook.
```

## Component responsibilities (spec §13)
| Spec component | Module | Notes |
|---|---|---|
| A. Market Monitor | `market_data/`, `monitoring/monitor.py` | timestamps, staleness, session status; never orders |
| B. Research & Strategy | `indicators/core.py`, `strategies/ma_trend.py` | explains for/against; abstains |
| C. Risk Manager | `risk/manager.py`, `risk/costs.py` | pure code; LLM cannot override |
| D. Execution Agent | `execution/executor.py`, `execution/manual_ticket.py` | approval, idempotency, timeout reconciliation |
| E. Trade Journal | `journal/store.py` | every proposal/decision/approval/fill |
| F. Supervisor | `workflows/supervisor.py` | ordering, halting |

## Key invariants (each has a test)
1. No order without `RiskDecision.approved`.
2. A live adapter is refused unless mode=live, flag=true, the acknowledgement
   phrase is set, AND an explicit per-order "yes" matches the intent id.
3. Same `intent_id` never creates a second order (paper DB primary key).
4. A timeout triggers a status lookup, never a resubmit.
5. Indicators at row t are identical whether or not later rows exist.
6. Backtest fills happen on the next bar; tampering with later bars cannot
   change an earlier entry.
7. The autopilot cannot be constructed with a live adapter, and its entries
   pass the same RiskManager (kill switch, cooldown and limits included).
8. A replay never writes to `state/paper.db` and is deterministic.
