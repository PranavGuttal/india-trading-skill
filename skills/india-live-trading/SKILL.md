---
name: india-live-trading
description: >-
  REAL-MONEY NSE orders through the Groww MCP connector, locked behind a
  graduation test, every live switch, the risk manager, an explicit per-order
  yes, and a guard hook that blocks any Groww order call not matching an
  approved ticket. Use only when the user explicitly asks to trade with real
  money, "go live", "place a real order on Groww", or asks whether live
  trading is unlocked. Otherwise use the paper skills.
---

# india-live-trading

Real money. Follow every step; if any step fails, stop and say why.

## 0. Is it unlocked?

```bash
python -m india_trading.cli live status
```

If GRADUATION is NOT PASSED or live switches are off, say so, list the
reasons it prints, and stop. Do not suggest editing settings, lowering
minimums, resetting the journal or any other way around the lock.
Graduation = ≥30 closed PAPER trades on ≥20 days, positive after charges,
every entry on real data with a live-read price and an APPROVED record.

## 1. Groww tools (first time, and whenever the connector changes)

List the Groww tools and read each input schema. Never guess names. Help the
user fill `config/groww_tools.yaml` (read_only vs order_tools, field mapping).
Until a tool is classified, the guard hook denies it. Modify/cancel tools are
never read_only.

## 2. One live entry

1. Read with read-only tools: the price (note the time) and available cash.
2. `live prepare SYMBOL --price P --price-source groww-mcp --cash C`
3. Show the user the whole ticket. Ask: "Place this REAL order? (yes/no)".
4. Only if the user's own reply is an explicit yes for this ticket:
   `live approve INTENT_ID --reply "<their exact words>"`. Never approve on
   their behalf, never reuse an earlier yes. "ok", "sure", "go" are not yes.
5. Within 5 minutes, call the Groww order tool with EXACTLY the ticket's
   symbol, side, quantity and LIMIT price. The guard hook checks it and
   Claude Code asks the user to confirm. Never send a market order.
6. Read the order status with a read-only tool, then
   `live record INTENT_ID --status FILLED --order-id ID --filled-qty N --avg-price X`.
   If the status is unclear, record UNKNOWN and tell the user to check the
   Groww app. Never resend.

## 3. Exits

`live exit SYMBOL --price P --price-source groww-mcp --reason stop|target|trend|max-hold`,
then the same approve → send → record steps. Exits need the live switches
but not graduation. If anything is locked, tell the user to sell in the app.

## Always

- `kill-switch on` blocks new live entries immediately.
- The ₹ budget in settings is enforced by this app only; Groww does not
  ring-fence it. Charges and gaps can make losses bigger than planned.
- No PINs, OTPs, TOTP secrets or tokens in chat or files, ever.
- Not investment advice. Report numbers from the tools only.
