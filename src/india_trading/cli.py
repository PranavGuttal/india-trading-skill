"""Command-line interface.  python -m india_trading.cli <command>

Every command says what it does. Nothing here sends a real order: the only
broker wired in is the paper broker.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from .analysis.breadth import compute as compute_breadth, format_breadth
from .backtesting.engine import format_report, run_backtest
from .brokers.paper_broker import PaperBroker
from .config import ConfigError, Settings, load_settings
from .journal.review import format_review, review
from .live.desk import LiveDesk, graduation_for
from .live.graduation import format_graduation
from .live.guard import load_tools
from .live.ledger import LedgerError
from .journal.store import Journal
from .logging_setup import setup_logging
from .market_data.calendar import IST, NSECalendar
from .market_data.csv_source import DataError, load_csv
from .market_data.importer import import_csv
from .market_data.yahoo_source import SOURCE as YAHOO_SOURCE, fetch_to_csv
from .models import OrderIntent, Quote, Side
from .monitoring.monitor import Monitor
from .risk.costs import estimate_charges
from .risk.manager import KillSwitch, RiskManager
from .simulation.replay import format_replay, run_replay
from .simulation.timemachine import format_result, simulate
from .strategies import ma_trend
from .workflows.autopilot import AutoPilot, format_tick
from .workflows.supervisor import Step, Supervisor

PAPER_BANNER = "[PAPER MODE — simulated only, nothing is sent to Groww]"


def _ctx(args):
    s = load_settings(args.config)
    if s.trading_mode == "live" or s.live_trading_enabled:
        print("WARNING: live settings detected, but this release has NO live broker adapter. "
              "All execution stays on the paper broker.", file=sys.stderr)
    cal = NSECalendar.from_yaml(Path("config") / "nse_holidays.yaml")
    journal = Journal(s.state_path("journal.db"))
    return s, cal, journal


def _data_path(s: Settings, args, symbol: str) -> Path:
    base = Path(getattr(args, "data_dir", None) or s.data_dir)
    return base / f"{symbol.upper()}.csv"


def _broker(s: Settings, quote_fn=None) -> PaperBroker:
    return PaperBroker(s.state_path("paper.db"), s.max_experimental_allocation_inr, s.charges,
                       price_provider=quote_fn, slippage_bps=s.slippage_bps)


def _quote_and_now(args, df: pd.DataFrame, symbol: str):
    if args.price is not None:
        now = datetime.now(IST)
        q = Quote(symbol=symbol, price=float(args.price), timestamp=now, source=f"manual:{args.price_source}")
        return q, now, False
    # REPLAY: pretend we are at 15:20 IST on the last bar's date and the close is the price
    d = pd.Timestamp(df["date"].iloc[-1]).date()
    now = datetime.combine(d, time(15, 20), tzinfo=IST)
    q = Quote(symbol=symbol, price=float(df["close"].iloc[-1]), timestamp=now, source="replay:last-close (NOT live)")
    return q, now, True


def _study(s: Settings, args) -> Settings:
    """--capital: a larger PAPER budget to study the strategy. Never a suggestion to trade that amount."""
    if not getattr(args, "capital", None):
        return s
    risk = args.risk or args.capital * 0.01
    return s.model_copy(update={
        "max_experimental_allocation_inr": args.capital, "max_single_order_value_inr": args.capital,
        "max_risk_per_trade_inr": risk, "daily_loss_limit_inr": min(args.capital, risk * 3),
        "weekly_loss_limit_inr": None, "monthly_loss_limit_inr": None,
    })


# ---------------------------------------------------------------- commands
def cmd_status(args):
    s, cal, journal = _ctx(args)
    now = datetime.now(IST)
    st = cal.status(now)
    print(PAPER_BANNER)
    print(json.dumps({
        "trading_mode": s.trading_mode, "live_trading_enabled": s.live_trading_enabled,
        "live_requested_all_switches": s.live_requested, "live_adapter_available": False,
        "require_human_approval": s.require_human_approval,
        "budget_inr": s.max_experimental_allocation_inr, "max_order_inr": s.max_single_order_value_inr,
        "max_open_positions": s.max_open_positions, "kill_switch": KillSwitch(s.state_path("KILL_SWITCH")).engaged,
        "nse_session": st.reason, "holidays_verified": st.holidays_verified,
        "charges_source": f"{s.charges.source} as of {s.charges.as_of}",
    }, indent=2))


def cmd_market_check(args):
    s, cal, _ = _ctx(args)
    now = datetime.now(IST)
    st = cal.status(now)
    print(f"{now:%Y-%m-%d %H:%M} IST — NSE {st.reason}. Market open: {st.is_open}.")
    if not st.holidays_verified:
        print("NOTE: add this year's NSE holidays to config/nse_holidays.yaml (from the official NSE circular).")
    print("Regime data (Nifty breadth, India VIX) is not wired yet: no verified free source. See docs/DATA_SOURCES.md.")


def cmd_analyze(args):
    s, cal, journal = _ctx(args)
    sup = Supervisor(s, _broker(s), journal, cal)
    as_of = pd.Timestamp(args.as_of).date() if args.as_of else None
    today = as_of or datetime.now(IST).date()
    st = sup.analyze(args.symbol.upper(), _data_path(s, args, args.symbol), today, as_of=as_of)
    p = st.proposal
    if st.step == Step.HALTED:
        print("HALTED:", st.halted_reason)
        return 2
    print(f"{p.symbol} | {p.strategy} v{p.strategy_version} | data {p.data_source} as of {p.as_of:%Y-%m-%d}")
    print("DECISION:", p.decision)
    for r in p.reasons:
        print("  +" if p.decision == "TRADE" else "  -", r)
    for c in p.contra:
        print("  (other)", c)
    if p.decision == "TRADE":
        print(f"  entry ₹{p.entry}  stop ₹{p.stop}  target ₹{p.target}  max hold {p.max_hold_days}d")
        print("  This is a research output, not advice. Run `paper start` to send it through the risk manager.")
    for line in st.log:
        if line.startswith("data warning"):
            print(" ", line)
    return 0


def cmd_scan(args):
    s, cal, journal = _ctx(args)
    base = Path(args.data_dir or s.data_dir)
    files = sorted(base.glob("*.csv"))
    if not files:
        print(f"No CSV files in {base}. Run `python scripts/make_sample_data.py` or add real data.")
        return 1
    for f in files:
        try:
            df, rep, src = load_csv(f, f.stem, cal)
        except DataError as e:
            print(f"{f.stem:14} ERROR {e}")
            continue
        if not rep.ok:
            print(f"{f.stem:14} INVALID {'; '.join(rep.errors)}")
            continue
        p = ma_trend.evaluate(df, f.stem, src)
        print(f"{f.stem:14} {p.decision:8} {('; '.join(p.reasons))[:110]}")
    return 0


def cmd_backtest(args):
    s, cal, _ = _ctx(args)
    s = _study(s, args)
    path = _data_path(s, args, args.symbol)
    df, rep, src = load_csv(path, args.symbol, cal)
    if not rep.ok:
        print("INVALID DATA:", rep.errors)
        return 2
    res = run_backtest(df, args.symbol.upper(), s, ma_trend.evaluate, src)
    print(format_report(res))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([t.__dict__ for t in res.trades]).to_csv(out, index=False)
        print(f"trades written to {out}")
    return 0


def cmd_paper_start(args):
    s, cal, journal = _ctx(args)
    sym = args.symbol.upper()
    path = _data_path(s, args, sym)
    try:
        df, _, _ = load_csv(path, sym, cal)
    except DataError as e:
        print("HALTED:", e)
        return 2
    as_of = pd.Timestamp(args.as_of).date() if args.as_of else None
    if as_of is not None:
        if args.price is not None:
            print("--as-of is a historical replay; it cannot be combined with --price.")
            return 2
        df = df[df["date"].dt.date <= as_of]
        if df.empty:
            print(f"No bars on or before {as_of}.")
            return 2
    quote, now, replay = _quote_and_now(args, df, sym)
    print(PAPER_BANNER)
    if replay:
        print(f"REPLAY: deciding as of {now:%Y-%m-%d %H:%M} IST using the last close ₹{quote.price} — not a live price.")
    broker = _broker(s, lambda _sym: quote)
    sup = Supervisor(s, broker, journal, cal)

    def approve(ticket: str, intent_id: str):
        print(ticket)
        if args.approve:
            return args.approve
        try:
            return input("Type 'yes' to place this PAPER order (anything else declines): ").strip()
        except EOFError:
            return None

    st = sup.run_once(sym, path, quote, now, approve=approve, as_of=as_of)
    if st.decision is not None and not st.decision.approved:
        print(st.ticket)
    for line in st.log:
        print(" ", line)
    print("RESULT:", st.step.value, st.halted_reason or st.execution_status)
    return 0 if st.step == Step.DONE else 1


def cmd_paper_status(args):
    s, _, _ = _ctx(args)
    b = _broker(s)
    print(PAPER_BANNER)
    print(f"Paper cash ₹{b.cash():.2f} (started with ₹{s.max_experimental_allocation_inr:.2f})")
    for p in b.get_positions():
        print(f"  {p.symbol} qty {p.qty} @ ₹{p.avg_price:.2f}  stop {p.stop}  target {p.target}")
    for t in b.closed_trades()[-10:]:
        print(f"  closed {t['symbol']} {t['qty']} {t['entry']}→{t['exit']} net ₹{t['pnl_net']} ({t['closed_at'][:10]})")


def cmd_paper_close(args):
    s, cal, journal = _ctx(args)
    sym = args.symbol.upper()
    df, _, _ = load_csv(_data_path(s, args, sym), sym, cal)
    if args.as_of:
        df = df[df["date"].dt.date <= pd.Timestamp(args.as_of).date()]
    quote, now, replay = _quote_and_now(args, df, sym)
    b = _broker(s, lambda _s: quote)
    pos = next((p for p in b.get_positions() if p.symbol == sym), None)
    if pos is None:
        print(f"No paper position in {sym}.")
        return 1
    intent = OrderIntent(symbol=sym, side=Side.SELL, qty=pos.qty, limit_price=round(quote.price * 0.995, 2),
                         product=s.product, trade_date=str(now.date()), proposal_ref=f"manual-exit:{now.isoformat()}")
    o = b.place_order(intent)
    journal.record("EXIT", "paper", f"{o.status.value} SELL {o.filled_qty} {sym} @ {o.avg_fill_price}", symbol=sym,
                   intent_id=o.intent_id, payload=o.model_dump(mode="json"))
    print(PAPER_BANNER, f"{o.status.value}: sold {o.filled_qty} {sym} at ₹{o.avg_fill_price} ({quote.source})")


def cmd_journal(args):
    s, _, journal = _ctx(args)
    if args.export:
        n = journal.export_csv(args.export, mode=args.mode)
        print(f"exported {n} events to {args.export}")
        return 0
    for e in reversed(journal.events(mode=args.mode, limit=args.limit)):
        print(f"{e['ts'][:19]} {e['mode']:5} {e['kind']:16} {e['symbol'] or '':12} {(e['summary'] or '').replace(chr(10), ' | ')[:100]}")


def cmd_risk_status(args):
    s, _, _ = _ctx(args)
    b = _broker(s)
    today = str(datetime.now(IST).date())
    a = b.get_account_state(today)
    print(PAPER_BANNER)
    print(json.dumps({
        "kill_switch": KillSwitch(s.state_path("KILL_SWITCH")).engaged,
        "cash": round(a.cash_available, 2), "open_positions": a.open_positions, "pending_orders": a.pending_orders,
        "realised_pnl_today": a.realised_pnl_today, "trades_today": a.trades_today,
        "limits": {"budget": s.max_experimental_allocation_inr, "max_order": s.max_single_order_value_inr,
                   "risk_per_trade": s.max_risk_per_trade_inr, "daily_loss_limit": s.daily_loss_limit_inr,
                   "max_trades_per_day": s.max_trades_per_day, "max_open_positions": s.max_open_positions},
    }, indent=2))


def cmd_kill(args):
    s, _, journal = _ctx(args)
    k = KillSwitch(s.state_path("KILL_SWITCH"))
    if args.state == "on":
        k.engage(args.reason or "manual")
        journal.record("KILL_SWITCH", "paper", "engaged: " + (args.reason or "manual"))
        print("Kill switch ENGAGED: no new orders until you run `kill-switch off`.")
    else:
        k.release()
        journal.record("KILL_SWITCH", "paper", "released")
        print("Kill switch released.")


def cmd_monitor(args):
    s, cal, journal = _ctx(args)
    m = Monitor(s, journal, cal, Path(args.data_dir or s.data_dir))
    if args.action == "stop":
        m.request_stop()
        print("Stop requested; a running monitor exits at its next tick.")
        return 0
    setup_logging()
    print(f"Monitor (read-only, no orders) polling every {args.interval}s. Ctrl+C or `monitor stop` to end.")
    m.run(interval_s=args.interval, max_ticks=args.ticks)
    print(Path(m.heartbeat).read_text(encoding="utf-8"))


def cmd_timemachine(args):
    s, cal, _ = _ctx(args)
    sym = args.symbol.upper()
    df, rep, src = load_csv(_data_path(s, args, sym), sym, cal)
    if not rep.ok:
        print("INVALID DATA:", rep.errors)
        return 2
    if args.as_of:
        df = df[df["date"].dt.date <= pd.Timestamp(args.as_of).date()].reset_index(drop=True)
    levels = (args.entry, args.stop, args.target)
    if None in levels:
        if any(v is not None for v in levels):
            print("Give all of --entry, --stop and --target, or none (then the strategy's plan is used).")
            return 2
        p = ma_trend.evaluate(df, sym, src)
        if p.decision != "TRADE":
            print(f"{sym}: strategy says NO_TRADE as of {p.as_of:%Y-%m-%d} ({'; '.join(p.reasons)[:160]}).")
            print("Nothing to simulate. To test your own plan pass --entry --stop --target.")
            return 1
        levels = (p.entry, p.stop, p.target)
    entry, stop, target = levels
    qty = args.qty or RiskManager(s).size_position(entry, stop)
    if qty < 1:
        print(f"NOTE: at the ₹{s.max_experimental_allocation_inr:.0f} budget the risk manager sizes 0 shares; simulating 1 share.")
        qty = 1
    try:
        r = simulate(df, sym, entry, stop, target, s, qty=qty, max_hold_days=args.hold, paths=args.paths,
                     lookback=args.lookback, seed=args.seed, data_source=src)
    except ValueError as e:
        print("CANNOT SIMULATE:", e)
        return 2
    print(format_result(r))
    return 0


def _parse_prices(text: str, source: str) -> dict[str, Quote]:
    now = datetime.now(IST)
    out = {}
    for part in filter(None, (x.strip() for x in text.split(","))):
        sym, _, px = part.partition("=")
        out[sym.strip().upper()] = Quote(symbol=sym.strip().upper(), price=float(px), timestamp=now,
                                         source=f"manual:{source}")
    return out


def cmd_autopilot(args):
    s, cal, journal = _ctx(args)
    s = s.model_copy(update={"data_dir": args.data_dir or s.data_dir})
    pilot = AutoPilot(s, _broker(s), journal, cal, s.data_dir)
    print(PAPER_BANNER)
    if args.prices:
        quotes, now, as_of = _parse_prices(args.prices, args.price_source), datetime.now(IST), None
    else:
        frames = pilot.load_frames()
        if not frames:
            print(f"No valid watchlist CSVs in {s.data_dir}.")
            return 1
        last = max(df["date"].iloc[-1].date() for df in frames.values())
        now, as_of = datetime.combine(last, time(15, 20), tzinfo=IST), last
        quotes = {sym: Quote(symbol=sym, price=float(df["close"].iloc[-1]), timestamp=now,
                             source="replay:last-close (NOT live)")
                  for sym, df in frames.items() if df["date"].iloc[-1].date() == last}
        print(f"REPLAY TICK as of {last} 15:20 IST using last closes — not live prices.")
    print(format_tick(pilot.tick(now, quotes, as_of=as_of)))
    return 0


def cmd_replay(args):
    s, cal, _ = _ctx(args)
    s = _study(s, args)
    if args.symbols:
        s = s.model_copy(update={"watchlist": [x.strip().upper() for x in args.symbols.split(",") if x.strip()]})
    start = pd.Timestamp(args.start).date() if args.start else None
    end = pd.Timestamp(args.end).date() if args.end else None
    try:
        r = run_replay(s, args.data_dir or s.data_dir, start, end, args.out or s.state_path("replay"), cal)
    except ValueError as e:
        print("CANNOT REPLAY:", e)
        return 2
    print(PAPER_BANNER)
    print(format_replay(r))
    return 0


def cmd_breadth(args):
    s, cal, _ = _ctx(args)
    frames = {}
    for f in sorted(Path(args.data_dir or s.data_dir).glob("*.csv")):
        try:
            df, rep, _ = load_csv(f, f.stem, cal)
        except DataError:
            continue
        if rep.ok:
            frames[f.stem] = df
    as_of = pd.Timestamp(args.as_of).date() if args.as_of else None
    print(format_breadth(compute_breadth(frames, as_of)))
    return 0


def cmd_review(args):
    s, _, journal = _ctx(args)
    print(format_review(review(_broker(s).closed_trades(), journal.events(mode="paper", limit=1_000_000))))
    return 0


def cmd_costs(args):
    s, _, _ = _ctx(args)
    value = args.price * args.qty
    lines = [f"CHARGES ({args.product}) for {args.qty} x ₹{args.price:.2f} = ₹{value:.2f} | "
             f"schedule {s.charges.source} as of {s.charges.as_of}"]
    total = 0.0
    for side in ("BUY", "SELL"):
        b = estimate_charges(value, side, args.product, s.charges)
        total += b.total
        lines.append(f"  {side:4} ₹{b.total:.2f}  (brokerage {b.brokerage:.2f}, STT {b.stt:.2f}, stamp {b.stamp:.2f}, "
                     f"exchange {b.exchange:.2f}, SEBI {b.sebi:.4f}, IPFT {b.ipft:.4f}, DP {b.dp:.2f}, GST {b.gst:.2f})")
    lines.append(f"  Round trip ≈ ₹{total:.2f} = {total / value:.1%} of the position. "
                 f"Break-even move ≈ ₹{total / args.qty:.2f}/share.")
    if args.stop is not None and args.target is not None:
        risk = args.qty * (args.price - args.stop) + total
        reward = args.qty * (args.target - args.price) - total
        lines.append(f"  Loss at stop incl. charges ₹{risk:.2f} | reward at target after charges ₹{reward:.2f}"
                     f" | limit per trade ₹{s.max_risk_per_trade_inr:.2f}")
    lines.append("  Estimates only; the contract note is the source of truth.")
    print("\n".join(lines))
    return 0


def cmd_data_import(args):
    s, cal, _ = _ctx(args)
    try:
        out, warnings = import_csv(args.file, args.symbol, args.out, args.source, cal, args.series)
    except (DataError, FileNotFoundError) as e:
        print("IMPORT FAILED:", e)
        return 2
    print(f"wrote {out} (source={args.source})")
    for w in warnings:
        print("  warning:", w)
    return 0


def cmd_live(args):
    s, cal, journal = _ctx(args)
    desk = LiveDesk(s, journal, cal, args.data_dir or s.data_dir)
    print("[LIVE DESK — real-money path; nothing is sent from here. Orders go through the Groww connector, "
          "checked by the guard hook.]")
    if args.lcmd == "status":
        tools = load_tools()
        print(json.dumps({"live_switches_on": s.live_requested, "trading_mode": s.trading_mode,
                          "live_trading_enabled": s.live_trading_enabled,
                          "kill_switch": KillSwitch(s.state_path("KILL_SWITCH")).engaged,
                          "budget_inr": s.max_experimental_allocation_inr,
                          "groww_read_only_tools": sorted(tools["read_only"]),
                          "groww_order_tools": sorted(tools["order_tools"]),
                          "ledger_positions": desk.ledger.positions()}, indent=2, default=str))
        print(format_graduation(graduation_for(s, journal)))
        return 0
    if args.lcmd == "tickets":
        for t in desk.ledger.tickets(args.limit):
            print(f"{t['created_at'][:19]} {t['status']:16} {t['kind']:5} {t['side']} {t['qty']} {t['symbol']} "
                  f"@ ₹{t['limit_price']}  {t['intent_id']}  {t['broker_order_id'] or ''}")
        return 0
    if args.lcmd in ("prepare", "exit"):
        if args.lcmd == "prepare":
            r = desk.prepare_entry(args.symbol, args.price, args.price_source, args.cash)
        else:
            r = desk.prepare_exit(args.symbol, args.price, args.price_source, args.reason)
        print(r.message)
        if r.text:
            print(r.text)
        for why in r.reasons:
            print("  -", why)
        if r.ok:
            print("NEXT: show this ticket to the user. Only if they reply an explicit yes for THIS order run "
                  f"`live approve {r.ticket['intent_id']}`; the approval expires in {s.live_approval_ttl_seconds}s.")
        return 0 if r.ok else 1
    try:
        if args.lcmd == "approve":
            reply = args.reply
            if reply is None:
                try:
                    reply = input("Type 'yes' to approve this REAL-MONEY order (anything else declines): ").strip()
                except EOFError:
                    reply = ""
            t = desk.ledger.approve(args.intent_id, reply, datetime.now(IST))
            journal.record("APPROVED", "live", f"reply: {reply[:60]}", symbol=t["symbol"], intent_id=t["intent_id"])
            print(f"APPROVED {t['side']} {t['qty']} {t['symbol']} @ ₹{t['limit_price']} until "
                  f"+{s.live_approval_ttl_seconds}s. Send exactly this order through the Groww order tool.")
            return 0
        if args.lcmd == "record":
            t = desk.ledger.record(args.intent_id, args.status.upper(), args.order_id, args.filled_qty, args.avg_price,
                                   args.note or "")
            journal.record("FILL" if t["filled_qty"] else "ORDER_STATUS", "live",
                           f"{t['status']} {t['side']} {t['filled_qty']}/{t['qty']} {t['symbol']} @ {t['avg_price']} "
                           f"(Groww order {t['broker_order_id']})", symbol=t["symbol"], intent_id=t["intent_id"])
            print(f"recorded {t['status']} for {t['intent_id']}")
            return 0
    except LedgerError as e:
        print("REFUSED:", e)
        return 2
    return 2


def cmd_data_fetch(args):
    s, cal, _ = _ctx(args)
    symbols = [x.strip().upper() for x in (args.symbols or []) if x.strip()] or list(s.watchlist)
    if any(sym.startswith("SYNTH_") for sym in symbols):
        print("SYNTH_* are synthetic sample symbols, not NSE listings. Give real NSE symbols, e.g. INFY TCS.")
        return 2
    print(f"Downloading {len(symbols)} NSE symbol(s) from {YAHOO_SOURCE}, {args.years}y daily, into {args.out} ...")
    bad = 0
    for sym, status, msgs in fetch_to_csv(symbols, args.out, args.years, cal):
        bad += status != "OK"
        print(f"  {sym:12} {status:7} {msgs[0] if msgs else ''}")
        for m in msgs[1:]:
            print(f"  {'':12} warning: {m}")
    print("Unofficial free data for personal research; re-run after 18:00 IST for the latest close.")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="india_trading", description="NSE research + paper-trading toolkit (no live orders).")
    ap.add_argument("--config", default="config/settings.yaml", help="YAML settings (optional)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show mode, limits and NSE session").set_defaults(fn=cmd_status)
    sub.add_parser("market-check", help="NSE session status").set_defaults(fn=cmd_market_check)
    p = sub.add_parser("scan", help="run the strategy on every CSV in the data dir")
    p.add_argument("--data-dir"); p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("analyze", help="analyse one symbol from its CSV (no orders)")
    p.add_argument("symbol"); p.add_argument("--data-dir")
    p.add_argument("--as-of", help="historical replay: use only bars up to this date (YYYY-MM-DD)")
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("backtest", help="backtest ma_trend_pullback on one CSV")
    p.add_argument("symbol"); p.add_argument("--data-dir"); p.add_argument("--capital", type=float)
    p.add_argument("--risk", type=float, help="max ₹ risk per trade (default 1% of capital)")
    p.add_argument("--out", help="write trades CSV"); p.set_defaults(fn=cmd_backtest)

    paper = sub.add_parser("paper", help="paper trading (simulated)")
    psub = paper.add_subparsers(dest="pcmd", required=True)
    for name, fn, h in [("start", cmd_paper_start, "analyse -> risk -> ticket -> approve -> simulated order"),
                        ("close", cmd_paper_close, "close a paper position at a price")]:
        q = psub.add_parser(name, help=h)
        q.add_argument("symbol"); q.add_argument("--data-dir")
        q.add_argument("--price", type=float, help="current price you read (e.g. from Groww); omit for REPLAY of last close")
        q.add_argument("--price-source", default="user-entered", help="where --price came from, e.g. groww-mcp")
        q.add_argument("--as-of", help="historical replay: use only bars up to this date (YYYY-MM-DD)")
        if name == "start":
            q.add_argument("--approve", help="non-interactive approval text for PAPER orders, e.g. yes")
        q.set_defaults(fn=fn)
    psub.add_parser("status", help="paper cash, positions, closed trades").set_defaults(fn=cmd_paper_status)

    p = sub.add_parser("journal", help="show or export the journal")
    p.add_argument("--mode", choices=["paper", "live", "backtest"]); p.add_argument("--limit", type=int, default=30)
    p.add_argument("--export", help="CSV path"); p.set_defaults(fn=cmd_journal)
    sub.add_parser("risk-status", help="limits and today's usage").set_defaults(fn=cmd_risk_status)
    p = sub.add_parser("kill-switch", help="block all new orders (on) or allow them again (off)")
    p.add_argument("state", choices=["on", "off"]); p.add_argument("--reason"); p.set_defaults(fn=cmd_kill)
    p = sub.add_parser("monitor", help="read-only polling monitor")
    p.add_argument("action", choices=["start", "stop"]); p.add_argument("--interval", type=int, default=300)
    p.add_argument("--ticks", type=int, help="stop after N ticks"); p.add_argument("--data-dir")
    p.set_defaults(fn=cmd_monitor)
    p = sub.add_parser("timemachine", help="Monte-Carlo odds of one long plan (stop vs target) from the stock's own daily bars")
    p.add_argument("symbol"); p.add_argument("--data-dir"); p.add_argument("--as-of")
    p.add_argument("--entry", type=float); p.add_argument("--stop", type=float); p.add_argument("--target", type=float)
    p.add_argument("--qty", type=int, help="default: what the risk manager would size")
    p.add_argument("--hold", type=int, default=ma_trend.PARAMS.max_hold_days, help="max hold days")
    p.add_argument("--paths", type=int, default=10_000); p.add_argument("--lookback", type=int, default=250)
    p.add_argument("--seed", type=int, default=19); p.set_defaults(fn=cmd_timemachine)
    p = sub.add_parser("autopilot", help="one unattended PAPER tick: manage exits, then auto-approved paper entries")
    p.add_argument("--data-dir")
    p.add_argument("--prices", help="current prices, e.g. INFY=1520.5,TCS=3901 (omit for a replay tick at the last close)")
    p.add_argument("--price-source", default="user-entered", help="where --prices came from, e.g. groww-mcp")
    p.set_defaults(fn=cmd_autopilot)
    p = sub.add_parser("replay", help="run the paper autopilot day by day over past data (separate state)")
    p.add_argument("--data-dir"); p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--symbols", help="comma list; default: watchlist")
    p.add_argument("--capital", type=float); p.add_argument("--risk", type=float)
    p.add_argument("--out", help="output folder (default state/replay; replaced each run)")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("breadth", help="watchlist breadth and regime (not NSE-wide)")
    p.add_argument("--data-dir"); p.add_argument("--as-of"); p.set_defaults(fn=cmd_breadth)
    sub.add_parser("review", help="performance review of closed paper trades + journal").set_defaults(fn=cmd_review)
    p = sub.add_parser("costs", help="Groww charge breakdown and break-even for a trade size")
    p.add_argument("price", type=float); p.add_argument("--qty", type=int, default=1)
    p.add_argument("--product", choices=["delivery", "intraday"], default="delivery")
    p.add_argument("--stop", type=float); p.add_argument("--target", type=float); p.set_defaults(fn=cmd_costs)
    p = sub.add_parser("data-import", help="normalise an exported daily-candle CSV into data/real/SYMBOL.csv")
    p.add_argument("file"); p.add_argument("symbol")
    p.add_argument("--source", required=True, help="where the file came from, e.g. nse-historical, groww-mcp")
    p.add_argument("--out", default="data/real"); p.add_argument("--series", default="EQ")
    p.set_defaults(fn=cmd_data_import)
    p = sub.add_parser("data-fetch", help="download real NSE daily candles (Yahoo Finance, unofficial) into data/real/")
    p.add_argument("symbols", nargs="*", help="NSE symbols, e.g. INFY TCS RELIANCE (default: watchlist)")
    p.add_argument("--years", type=int, default=5); p.add_argument("--out", default="data/real")
    p.set_defaults(fn=cmd_data_fetch)
    live = sub.add_parser("live", help="REAL-MONEY desk (locked until graduation + live switches); never sends orders itself")
    lsub = live.add_subparsers(dest="lcmd", required=True)
    q = lsub.add_parser("status", help="switches, graduation test, classified Groww tools, live positions")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("tickets", help="live tickets and their states"); q.add_argument("--limit", type=int, default=30)
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("prepare", help="analyse + risk-check + write a live BUY ticket (needs graduation)")
    q.add_argument("symbol"); q.add_argument("--price", type=float, required=True)
    q.add_argument("--price-source", required=True, help="e.g. groww-mcp (read just now)")
    q.add_argument("--cash", type=float, help="available cash read from Groww just now (required to pass)")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("exit", help="write a live SELL ticket for a live-ledger position")
    q.add_argument("symbol"); q.add_argument("--price", type=float, required=True)
    q.add_argument("--price-source", required=True); q.add_argument("--reason", default="manual")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("approve", help="explicit per-order yes for one PREPARED ticket")
    q.add_argument("intent_id"); q.add_argument("--reply", help="only the user's own words for THIS ticket")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("record", help="record the Groww result of a SENT ticket")
    q.add_argument("intent_id"); q.add_argument("--status", required=True,
                                                choices=["FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELLED", "UNKNOWN"])
    q.add_argument("--order-id"); q.add_argument("--filled-qty", type=int, default=0)
    q.add_argument("--avg-price", type=float); q.add_argument("--note"); q.add_argument("--data-dir")
    q.set_defaults(fn=cmd_live)
    return ap


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):   # Windows pipes default to cp1252, which cannot print ₹
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except ConfigError as e:
        print("CONFIG ERROR:", e, file=sys.stderr)
        return 2
    except DataError as e:
        print("DATA ERROR:", e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
