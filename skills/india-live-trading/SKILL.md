---
name: india-live-trading
description: >-
  REAL-MONEY NSE orders through Groww, locked behind a graduation test, every
  live switch, the risk manager, an explicit per-order yes, and (when Claude
  sends the order) a guard hook that only works in Claude Code. Use only when
  the user explicitly asks to trade with real money, "go live", "place a real
  order on Groww", or asks whether live trading is unlocked. Otherwise use the
  paper skills.
---

# india-live-trading

Real money. Follow every step; if any step fails, stop and say why.

## 0. Is it unlocked, and can Claude send from here?

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" live status
```

- If GRADUATION is NOT PASSED or the live switches are off, say so, list the
  reasons it prints, and stop. Do not suggest editing settings, lowering
  minimums, resetting the journal, or any other way around the lock.
- Read the `CLAUDE SEND PATH` line. AVAILABLE means this is Claude Code with
  the guard hook installed. UNAVAILABLE (for example in the Claude desktop or
  web app, where hooks do not run and state does not persist) means you must
  NOT call any Groww order tool: use `--send-via app` so the user places the
  order themselves.

Graduation = ≥30 closed PAPER trades on ≥20 days, positive after charges,
every entry on real data with a live-read price that matches that day's real
NSE bar, each with an APPROVED record.

## 1. Groww tools (first time, and whenever the connector changes)

List the Groww tools and read each input schema. Never guess names. Help the
user fill `config/groww_tools.yaml` (read_only vs order_tools, field mapping).
Until a tool is classified, the guard hook denies it. The guard checks every
MCP tool, so an order-like tool from a connector with any name is denied too
unless classified. Modify/cancel tools are never read_only.

## 2. One live entry

1. Read with read-only tools: the price (note the time) and available cash.
2. `live prepare SYMBOL --price P --price-source groww-mcp --cash C`
3. Show the user the whole ticket. Ask: "Place this REAL order? (yes/no)" and,
   if the send path is AVAILABLE, whether Claude should send it or they will
   place it in the Groww app.
4. Only if the user's own reply is an explicit yes for this ticket:
   `live approve INTENT_ID --reply "<their exact words>" --send-via claude`
   or `--send-via app`. Never approve on their behalf and never reuse an
   earlier yes. "ok", "sure" and "go" are not yes.
5. `--send-via claude`: within 5 minutes, call the Groww order tool with
   EXACTLY the ticket's symbol, side, quantity and LIMIT price. The guard hook
   checks it and Claude Code asks the user to confirm. Never send a market
   order. If you are not willing or able to send it, say so and switch to
   the app path. Do not try another tool or connector.
   `--send-via app`: tell the user to place exactly the ticket (LIMIT) in
   the Groww app now. Do not call any order tool for it.
6. Read the order status with a read-only tool, or ask the user for the Groww
   order details, then
   `live record INTENT_ID --status FILLED --order-id ID --filled-qty N --avg-price X`.
   If the status is unclear, record UNKNOWN and tell the user to check the
   Groww app. Never resend.

## 3. Exits

`live exit SYMBOL --price P --price-source groww-mcp --reason stop|target|trend|max-hold`,
then the same approve → send → record steps. Exits need the live switches
but not graduation. If anything is locked, tell the user to sell in the app.

## Always

- `kill-switch on` blocks new live entries immediately.
- No unattended live trading: the autopilot is paper-only, and every live
  order needs the user's own yes at that moment.
- The ₹ budget in settings is enforced by this app only; Groww does not
  ring-fence it. Charges and gaps can make losses bigger than planned.
- No PINs, OTPs, TOTP secrets or tokens in chat or files, ever.
- Not investment advice. Report numbers from the tools only.
