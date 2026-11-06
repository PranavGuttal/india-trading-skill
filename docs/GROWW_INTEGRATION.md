# Groww integration

## Confirmed (from Groww's own pages, read 2026-10-30)
- Groww MCP server at `https://mcp.groww.in/mcp`, added in Claude as a custom
  connector; sign-in is Groww's OAuth page (product update, 4 Aug 2025).
- Groww describes it as "very early-stage tech", for stocks and F&O.
- Its examples include reading holdings/positions/charts and placing buy,
  limit and stop-loss orders; sell orders need DDPI.
- Groww Trade API is separate (`https://groww.in/trade-api`), priced
  separately; order placement requires a registered static IP (SEBI framework).
- Equity charges used in `risk/costs.py` come from `https://groww.in/pricing`.

## NOT verified (so not implemented)
- The MCP server's exact tool names, input schemas and outputs: the connector
  was not attached to the session that built this project, so they were not
  inspected. Guessing them is forbidden by this project's rules.
- Whether MCP quotes carry timestamps or are delayed.
- Order modification/cancellation, order-status, reconciliation and
  idempotency behaviour through MCP.
- Any broker-side capital limit or sub-account that could enforce the ₹200
  budget. **Assume there is none.**

## How Groww is used in this release
| Need | How |
|---|---|
| Holdings / positions | Ask Claude with the Groww connector on; read-only tools only |
| Prices for a paper decision | Claude reads a price via the connector → `paper start SYMBOL --price X --price-source groww-mcp` |
| Historical candles | Save connector chart data to `data/real/SYMBOL.csv` |
| Placing a real order | Locked live path below, or **you** place it in the Groww app from the printed ticket |

`brokers/groww_adapter.py` implements the adapter interface and raises
`UnsupportedOperation` for every method, with this explanation. The execution
agent also refuses any live adapter unless every live switch and a per-order
approval are present, so wiring an adapter later cannot silently enable trading.

## Locked live path (Groww MCP; hardened in 0.4.1)
Python cannot call MCP tools, so a real order is either sent by Claude through
the connector or placed by you in the Groww app. Both go through the same
gates:

1. `live prepare` (src/india_trading/live/desk.py) refuses unless all live
   switches are on, the kill switch is off, **graduation** passed, and the
   RiskManager approves using cash read from Groww. It writes a PREPARED
   ticket to `state/live.db`. Graduation needs at least 30 closed forward-paper
   trades on at least 20 days, positive after charges, all on real data. Every
   typed paper price must also fall inside that day's real NSE low–high range.
2. `live approve --send-via claude|app` needs your explicit per-order yes.
   - `claude`: allowed only when `live/runtime.py` confirms Claude Code
     (`CLAUDECODE=1`) and a guard hook covering all MCP tools. The approval
     expires in 5 minutes.
   - `app`: the ticket becomes APPROVED_APP. The guard never lets Claude
     send it, and you place it in the Groww app.
3. **Guard hook** (plugin `hooks/hooks.json` → `scripts/guard.sh` →
   `india.py --guard`; in this repo also `.claude/settings.json`). Matcher
   `mcp__.*`, so it sees every MCP call, whatever the connector is named:
   - an unclassified Groww tool is denied;
   - an order-like tool from any other connector is denied, unless listed
     under `allow_other`;
   - a classified order tool is denied unless its symbol, side, qty and limit
     price match one approved, unexpired, unsent ticket. Then it returns
     "ask", so Claude Code shows you a confirmation.
   - Errors deny, and `onFailure: block` covers crashes.
4. `live record` stores the Groww result for SENT and APPROVED_APP tickets.
   UNKNOWN means check the app; never resend.

`config/groww_tools.yaml` is empty on purpose: tool names and field mappings
must be filled in after listing the connector's real tools.

## Supported setup for real money: Claude Code on your PC
Hooks run only in Claude Code. In the Claude desktop or web app, skills run
in a temporary cloud sandbox: no guard hook, and no persistent paper account
or journal. Use the app for research if you like, but do real-money steps in
Claude Code:

1. Install the plugin (README → Install in Claude Code) and restart Claude Code.
2. Add the Groww connector to Claude Code. Name it `groww` so its tools appear
   as `mcp__groww__…`:
   `claude mcp add --transport http groww https://mcp.groww.in/mcp`.
   Then run `/mcp` inside Claude Code and sign in through Groww's page.
3. Ask Claude to list the Groww tools, then fill `config/groww_tools.yaml`
   together.
4. Run `live status`. It must show `CLAUDE SEND PATH: AVAILABLE`. If it shows
   UNAVAILABLE inside Claude Code, do not work around it: use `--send-via app`.

Known limits:
- You can still place any order directly in the Groww app.
- Groww may change tool names or schemas; re-run step 3 after connector updates.
- Claude may decline to send real-money orders itself. The app path covers that.
- The hook is unit-tested and pipe-tested, but it has not yet been observed
  against the real connector.

## Before enabling the live switches
1. Inspect the actual tool schemas (MCP) or API docs; record them here.
2. Implement read-only methods first; test against recorded responses.
3. Verify order-status lookup and how duplicate client order ids behave.
4. Add order placement behind the existing guards; keep paper as default.
5. Paper-trade for weeks; review the journal; only then consider live.
