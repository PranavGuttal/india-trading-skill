# Architecture

```
            ┌─────────────── Claude skills (skills/india-*) ───────────────┐
            │  instructions + CLI entry points; Groww connector READ-ONLY   │
            └───────────────────────────────┬──────────────────────────────┘
                                            │ python -m india_trading.cli …
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
Backtester (backtesting/engine.py): same strategy + same RiskManager, next-bar fills.
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
