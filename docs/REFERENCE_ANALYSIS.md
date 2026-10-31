# Reference analysis

Both repositories were cloned (shallow, read-only) on 2026-10-30 and inspected
at the source level. Neither was modified. **No code was copied**: every
module here is an independent implementation. Both are MIT licensed, so
reuse with the copyright notice would have been allowed; ideas were reused,
code was not, which is why no third-party notice is required. They are
credited here.

| Repo | License | Size inspected |
|---|---|---|
| `tradermonty/claude-trading-skills` | MIT © 2026 TraderMonty | 70+ skills, `workflows/*.yaml`, per-skill `scripts/` + `tests/` |
| `Jakeschincariol/day-trader-skill` | MIT © 2026 Jake Schincariol | 11 skills, ~8,600 lines of stdlib Python, offline fixture tests (1 commit) |

## 1. Useful patterns

### TraderMonty
| Pattern | Where | Decision |
|---|---|---|
| Skill per job with a narrow `description` trigger | `skills/*/SKILL.md` | **Reused conceptually** → 5 `skills/india-*` |
| Workflow manifests with `when_to_run` / `when_not_to_run` and a regime gate | `workflows/swing-opportunity-daily.yaml` | **Adapted**: the Supervisor state machine is the gate order; regime gate deferred until a verified India VIX/breadth source exists |
| Position sizer as pure calculation | `skills/position-sizer/scripts/position_sizer.py` | **Adapted** into `RiskManager.size_position` + cost-aware reduction |
| Pre-trade discipline gate that journals the decision | `skills/pre-trade-discipline-gate` | **Adapted**: every RISK_BLOCKED / APPROVED is journalled |
| Drawdown circuit breaker (daily loss, streak cooldown) | `skills/drawdown-circuit-breaker` | **Adapted**: daily, weekly and monthly loss limits, losing-streak cooldown, kill switch — in `RiskManager`, applied in paper, backtest and replay |
| Breadth / uptrend analysers | `skills/market-breadth-analyzer`, `uptrend-analyzer` | **Adapted** as watchlist-only breadth + optional autopilot regime gate (`analysis/breadth.py`); no NSE-wide source yet |
| Performance coach / signal postmortem | `skills/trade-performance-coach`, `signal-postmortem` | **Adapted** as `review` (`journal/review.py`) |
| Second-opinion subagent | `agents/strategy-reviewer.md` | **Adapted** as `agents/india-strategy-critic.md`; plus `india-risk-auditor` |
| Navigator skill | `skills/trading-skills-navigator` | **Adapted** as `india-trading-navigator` |
| Thesis lifecycle memory + postmortem | `skills/trader-memory-core` | **Adapted** into an event journal + notes table |
| Backtest critique ("beat ideas to death", sample size, overfitting) | `skills/backtest-expert` | **Reused conceptually**: train/test split, 30-trade minimum, baseline, INCONCLUSIVE verdicts |

### Day Trader Skill
| Pattern | Where | Decision |
|---|---|---|
| Risk check as the only gate to the broker, PASS/BLOCK with reasons, entries vs exits | `trader-risk/check.py` (`check()`), `SKILL.md` | **Adapted**: `RiskManager.evaluate`; exits are never blocked by entry limits |
| Order fingerprint to tie a verdict to the exact order | `trader-risk/check.py::fingerprint`, `trader-broker/ticket.py::fingerprint` | **Adapted** as `OrderIntent.intent_id` (also the idempotency key) |
| Explicit per-order "yes" that rejects "ok/sure/yes to all" | `trader-broker/ticket.py::parse_yes` | **Adapted** in `executor.Approval.is_explicit_yes` |
| Loss measured from the worse of plan entry and fresh price | `trader-risk/check.py` | **Reused conceptually** (`entry = max(plan, quote)`) |
| Exit planner: stop/target set before entry | `trader-exit/exit.py` | **Adapted** into the strategy proposal |
| Monte-Carlo "time machine" | `trader-timemachine/timemachine.py` | **Adapted** to daily NSE bars + Groww charges (`simulation/timemachine.py`, `india-time-machine`) |
| Broker step driven by Claude through an MCP connector | README (Alpaca MCP) | **Adapted, paper only**: Claude reads Groww prices read-only and runs `autopilot --prices`; orders stay simulated |
| Pelosi / SEC / Nasdaq scanners | `trader-pelosi`, `trader-news`, `trader-scanner` | **Omitted**: US-only data sources |
| Paper by default, keys in env, never in chat | README "Fine print" | **Reused** |

## 2. US → India differences that drove the design

| US assumption in the references | India requirement here |
|---|---|
| New York time, DST maths | IST (no DST), NSE 09:15–15:30 |
| NYSE/Nasdaq holidays computed in code | NSE holidays from the official circular in `config/nse_holidays.yaml` (not hard-coded, unverified until filled) |
| Alpaca MCP/REST, fractional & notional orders | Groww; whole shares only; no live adapter until capabilities are verified |
| Commission-free equities | ₹5 minimum brokerage, STT, stamp, exchange, SEBI, IPFT, GST, DP charge on delivery sells — modelled in `risk/costs.py` |
| PDT rule | Not applicable; Indian intraday auto square-off (₹50/position at Groww) noted, intraday not default |
| Yahoo/SEC/FMP free data | No verified free live NSE feed from this environment; local CSV first |
| Ticker = symbol | NSE symbol; instrument eligibility (series, ASM/GSM lists, price bands) NOT yet verified — documented gap |

## 3. Dependencies and licensing
- Runtime: pandas, numpy, pydantic, PyYAML, tzdata (Windows zoneinfo). Test: pytest.
- No dependency on either reference repo. If code is ever copied in, keep the
  MIT notice from the source file's repo in `THIRD_PARTY_NOTICES.md`.

## 4. Proposed architecture
See `ARCHITECTURE.md`. In short: CSV/broker data → validation → deterministic
indicators → one transparent strategy (may return NO_TRADE) → deterministic
risk manager with charges → ticket → explicit approval → paper broker
(idempotent, SQLite) → journal → reports. Live execution is a separate,
currently refused path.
