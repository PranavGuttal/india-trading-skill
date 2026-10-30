# Operations

## Daily paper routine (≈10 minutes)
1. `python -m india_trading.cli status` — confirm PAPER, limits, session.
2. `python -m india_trading.cli scan` — what is setting up (read-only).
3. For a TRADE candidate: read its current price (Groww app or connector),
   then `paper start SYMBOL --price <p> --price-source groww-app`.
4. Read the ticket. Type `yes` only if you agree with this exact order.
5. Later: `paper close SYMBOL --price <p>` when stop/target/time hits.
6. `journal --limit 30` and `paper status`; weekly `journal --export`.

## Monitor
`monitor start --interval 300` polls the watchlist CSVs, writes
`state/monitor_heartbeat.json`, and stops on Ctrl+C, `monitor stop`, or the
kill switch. Minimum interval 30 s. It places no orders and does nothing
while the process or computer is off.

## Recovery
- State is in `state/paper.db` and `state/journal.db`. Back them up by copying.
- After a crash just rerun: orders are keyed by intent id, so a repeated
  request returns the existing order instead of placing another.
- A broker timeout is logged as RECOVERY; the order's status is looked up,
  never resubmitted. If status is UNKNOWN, check the broker by hand.
- Reset paper trading: stop everything, delete `state/paper.db`.

## Security checklist
- [x] No credentials read or stored by this release; `.env` and `state/` git-ignored.
- [x] Journal payloads redact keys like token/secret/password/pin/otp/api_key/account id.
- [x] JSON log formatter redacts `token=…`, bearer tokens and JWT-looking strings.
- [x] Live adapter refuses all calls; executor refuses live without 3 switches + per-order yes.
- [x] Short selling, derivatives, leverage rejected at config load.
- [ ] Before any live work: secret store (Windows Credential Manager), static IP, audited adapter.
- Never paste PIN, OTP, TOTP secret or API tokens into chat or config.
