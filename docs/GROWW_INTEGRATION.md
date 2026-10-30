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
| Placing a real order | **You** place it in the Groww app from the printed ticket |

`brokers/groww_adapter.py` implements the adapter interface and raises
`UnsupportedOperation` for every method, with this explanation. The execution
agent also refuses any live adapter unless every live switch and a per-order
approval are present, so wiring an adapter later cannot silently enable trading.

## Before ever adding a live path
1. Inspect the actual tool schemas (MCP) or API docs; record them here.
2. Implement read-only methods first; test against recorded responses.
3. Verify order-status lookup and how duplicate client order ids behave.
4. Add order placement behind the existing guards; keep paper as default.
5. Paper-trade for weeks; review the journal; only then consider live.
