# Reference analysis and comparison

Two public repositories were read on GitHub (not cloned) on 2026-10-30/11-01:

| Repo | License | What it is |
|---|---|---|
| `tradermonty/claude-trading-skills` | MIT © 2026 TraderMonty | 74 US-market skills, 2 subagents, 12 workflow manifests, `claude -p` automation scripts. Research and journaling; "not an automated trading system"; workflows are followed by hand. |
| `Jakeschincariol/day-trader-skill` | MIT © 2026 Jake Schincariol | 11 US day-trading skills with stdlib Python (scanner, news, entry, exit, time machine, risk, budget, broker via Alpaca MCP, alerts, analyst, Pelosi trades). |

**No code was copied.** Every module here is an independent implementation;
ideas are credited below and in each module's docstring. No third-party
notice is needed. If code is ever copied, add the source repo's MIT notice
to `THIRD_PARTY_NOTICES.md`.

## What was adapted, and how it changed for India

| Idea (source) | Here | What is different |
|---|---|---|
| Skill per job, navigator (TM) | 27 `india-*` skills + navigator | each skill drives a tested Python command; a contract test parses every documented command |
| Second-opinion agents (TM strategy-reviewer, scenario-analyst) | `india-strategy-critic`, `india-scenario-analyst` | checklist incl. multiple testing and the holdout universe |
| News / analyst (DT trader-news, trader-analyst; TM market-news-analyst) | `india-news-analyst`, `india-results-analyst` | NSE/BSE filings first; every fact dated and sourced |
| Backtest expert (TM) | `lab` portfolio engine + single-stock backtest + replay | shared cash, max positions, Groww charges, earlier/later halves, holdout universe, buy & hold and Nifty benchmarks, survivorship warning |
| Edge pipeline / strategy designer (TM) | strategy registry, declarative rules + exit policies | the same rules run in lab, backtest, replay, autopilot and live desk |
| VCP / CANSLIM / momentum burst / episodic pivot (TM), scanner (DT) | `screen` + `trend_template` strategy | over the official Nifty 500 list (`universe-fetch`, NSE industries); technical half only; RS rank inside the universe |
| US stock analysis (TM) | `india-stock-analysis` | technical report + results agent (fundamentals from the filing) + actions + news + market gate |
| Institutional flow tracker (TM) | `india-flows-analyst` agent | FII/DII cash-market flows, NSDL FPI, bulk/block deals; sourced; no predictive claim |
| Breakout trade planner, position sizer (TM), budget, exit (DT) | `plan`, `size`, `exit-plan`, trailing stops | whole shares, loss at stop **includes** charges, break-even after charges |
| Market breadth / uptrend / FTD / distribution days / market top / exposure coach (TM) | `regime` + **market gate** | real Nifty 50 + India VIX; the 200-day trend filter is tested and now gates every new entry by default |
| Sector analyst / theme detector (TM) | `sectors` | 13 real NSE sector indices, RS vs Nifty |
| Portfolio manager, dividend review monitor (TM) | `portfolio`, `actions` | Groww holdings read-only; review triggers, never auto-sell |
| Drawdown circuit breaker, pre-trade gate (TM) | risk manager | daily/weekly/monthly limits, streak cooldown, **capital floor**, kill switch; one deterministic gate in every mode |
| Workflows (TM, manual) | `daily` | actually runs the routine and saves a dated report |
| Alerts (DT) | `alerts` | YAML rules + automatic position alerts; never orders |
| Time machine (DT) | `timemachine`, `plan --odds` | daily NSE bars, charges deducted, stop before target |
| Risk check + fingerprint + strict yes (DT) | risk manager, `intent_id`, `Approval.is_explicit_yes` | also idempotency key; approvals expire in 5 minutes |
| Broker via MCP (DT, Alpaca) | Groww MCP | read-only by default; order tools pass only a **PreToolUse guard hook** matching an approved single-use ticket, after graduation |
| Pelosi / SEC / Nasdaq / FINRA (DT, TM) | omitted | US-only data; India equivalents (SAST, bulk/block deals) are not readable by scripts |
| Options strategy advisor, futures, crypto, US tax (TM) | omitted | out of scope: cash equities only; derivatives and leverage are refused in config (SEBI: ~9 in 10 F&O traders lose) |

## Honest comparison

| | tradermonty | day-trader | this repo |
|---|---|---|---|
| Market | US | US | **India (NSE, Groww)** |
| Skills / agents | **74** / 2 | 11 / 0 | 27 / 6 |
| Breadth of analysis (fundamentals, options, macro, crypto) | **far wider** | narrow | technical + regime + sectors + portfolio |
| Real-money orders today | no | **yes (Alpaca)** | locked until graduation |
| Charges modelled | — | commission-free US | **Groww: brokerage min, STT, stamp, exchange, SEBI, IPFT, GST, DP** |
| One deterministic risk gate in every mode | partly (skills) | yes (check.py) | **yes, incl. capital floor, used by lab/backtest/replay/paper/live** |
| Unattended paper trading | no (manual workflows) | via Claude + Alpaca paper | **autopilot + allocation pilot, replay** |
| Strategies tested on 10 years of real data with a holdout set | not shown | not shown | **yes, all results published, including the failures** |
| Hook-level protection against an unapproved order call | no | no | **yes** |
| Automated tests | per-skill | offline fixtures | **300+, incl. a contract test of every skill command** |

So this repo is **not** bigger than tradermonty, and it does not trade real
money as freely as day-trader. It is deeper and safer for one market:
- every number comes from tested code;
- the same rules apply from research to the live desk;
- Indian costs are exact;
- it publishes that no strategy here beat buy & hold.

## US → India differences that drove the design

| US assumption in the references | India requirement here |
|---|---|
| New York time, DST maths | IST (no DST), NSE 09:15–15:30 |
| NYSE holidays computed in code | NSE holidays from the official list in `config/nse_holidays.yaml`, filled by hand (NSE's page refuses scripts) |
| Alpaca, fractional & notional orders | Groww; whole shares only; limit orders only |
| Commission-free equities | ₹5 minimum brokerage, STT, stamp, exchange, SEBI, IPFT, GST, DP charge on delivery sells (`risk/costs.py`); below ~₹25,000 only a single ETF is economical |
| PDT rule | not applicable; intraday auto square-off noted, delivery is the default |
| Free US data (Yahoo/SEC/FMP) | Yahoo Finance for NSE stocks, indices, ETFs (unofficial, end of day); NSE archives refuse scripts |
| Ticker = symbol | NSE symbol; series/ASM/GSM/price bands not yet checked (documented gap) |
