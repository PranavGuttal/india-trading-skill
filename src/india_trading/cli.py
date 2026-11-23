"""Command-line interface.  python -m india_trading.cli <command>

Every command says what it does. Nothing here sends a real order: the only
broker wired in is the paper broker.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
from .live.runtime import check as runtime_check
from .live.graduation import format_graduation
from .live.guard import load_tools
from .live.ledger import LedgerError
from .journal.store import Journal
from .logging_setup import setup_logging
from .market_data.calendar import IST, NSECalendar
from .market_data.csv_source import DataError, load_csv
from .market_data.importer import import_csv
from .market_data.yahoo_source import INDICES, SECTOR_INDICES, SOURCE as YAHOO_SOURCE, fetch_to_csv, load_events
from .models import OrderIntent, Quote, Side
from .monitoring.monitor import Monitor
from .risk.costs import estimate_charges
from .risk.manager import KillSwitch, RiskManager
from .simulation.replay import format_replay, run_replay
from .simulation.timemachine import format_result, simulate
from .strategies import SIGNAL_STRATEGIES, get as get_strategy, ma_trend
from .paths import PLUGIN_ROOT, config_file
from .workflows.autopilot import AutoPilot, format_tick
from .workflows.supervisor import Step, Supervisor

PAPER_BANNER = "[PAPER MODE — simulated only, nothing is sent to Groww]"


def _ctx(args):
    s = load_settings(args.config)
    if getattr(args, "strategy", None):
        get_strategy(args.strategy)                        # unknown name -> KeyError, reported by main()
        s = s.model_copy(update={"strategy": args.strategy})
    if s.trading_mode == "live" or s.live_trading_enabled:
        print("NOTE: live settings detected. Real orders exist only through the locked `live` desk and the "
              "guard hook; every other command stays on the paper broker.", file=sys.stderr)
    cal = NSECalendar.from_yaml(config_file("nse_holidays.yaml"))
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
    risk = args.risk or args.capital * s.risk_per_trade_pct / 100
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
        p = get_strategy(s.strategy).evaluate(df, f.stem, src)
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
    nifty = _index(s, "NIFTY50", required=False) if s.regime_gate == "index" else None
    if s.regime_gate == "index" and nifty is None:
        print("NOTE: market gate is off for this backtest: no Nifty 50 data (run `data-fetch --indices`).")
    res = run_backtest(df, args.symbol.upper(), s, get_strategy(s.strategy), src, regime_index=nifty)
    if nifty is not None:
        print("Market gate ON: no new entries while Nifty 50 was below its 200-day average.")
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


def _set_yaml_key(path: Path, key: str, value) -> None:
    """Set one top-level key in a YAML file, keeping every other line and comment."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pat = re.compile(rf"^{re.escape(key)}:[ \t]*[^\s#]*", re.M)
    if pat.search(text):
        text = pat.sub(f"{key}: {value}", text, count=1)
    else:
        text = text + ("" if not text or text.endswith("\n") else "\n") + f"{key}: {value}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _limits_lines(s: Settings) -> list[str]:
    fixed = set(s.explicit_limits)

    def how(field, pct):
        return "fixed ₹, does NOT scale with the budget" if field in fixed else f"{pct:g}% of budget"

    return [
        f"  budget             ₹{s.max_experimental_allocation_inr:,.2f}",
        f"  max order          ₹{s.max_single_order_value_inr:,.2f}  ({how('max_single_order_value_inr', s.max_single_order_pct)})",
        f"  risk per trade     ₹{s.max_risk_per_trade_inr:,.2f}  ({how('max_risk_per_trade_inr', s.risk_per_trade_pct)}, charges incl.)",
        f"  daily loss limit   ₹{s.daily_loss_limit_inr:,.2f}  ({how('daily_loss_limit_inr', s.daily_loss_pct)})",
        f"  weekly / monthly   ₹{s.weekly_loss_limit:,.2f} / ₹{s.monthly_loss_limit:,.2f}",
        f"  capital floor      ₹{s.capital_floor:,.2f}  ({s.capital_floor_pct:g}% of budget must survive)",
    ]


def cmd_budget(args):
    """Show the budget, its limits and paper performance; `budget set N` changes it."""
    s, _, journal = _ctx(args)
    if args.action == "set":
        if args.amount is None or args.amount <= 0:
            print("Give the new budget in rupees, e.g. `budget set 5000`.")
            return 2
        if "MAX_EXPERIMENTAL_ALLOCATION_INR" in os.environ:
            print("MAX_EXPERIMENTAL_ALLOCATION_INR is set in the environment and overrides the settings file; "
                  "change or remove it there instead.")
            return 2
        old = s.max_experimental_allocation_inr
        try:
            new = s.with_budget(args.amount)
        except Exception as e:                 # invalid combination, e.g. a fixed ₹ limit above the new budget
            raise ValueError(f"budget ₹{args.amount:,.2f} rejected: {e}") from e
        _broker(new)                           # moves paper cash by the difference; refuses if it cannot
        alloc_db = Path(s.state_dir) / "allocation" / "paper.db"
        if alloc_db.exists():
            PaperBroker(alloc_db, new.max_experimental_allocation_inr, new.charges)
        _set_yaml_key(Path(args.config), "max_experimental_allocation_inr", f"{args.amount:g}")
        journal.record("BUDGET", "paper", f"budget ₹{old:,.2f} -> ₹{args.amount:,.2f}",
                       payload={"old": old, "new": args.amount})
        print(f"Budget changed ₹{old:,.2f} → ₹{args.amount:,.2f} (saved in {args.config}). "
              f"Paper cash moved by the difference.")
        s = new
    print(PAPER_BANNER)
    print("Budget and limits:")
    print("\n".join(_limits_lines(s)))
    if s.explicit_limits:
        print(f"  NOTE: {', '.join(s.explicit_limits)} set as fixed ₹ in settings; "
              f"blank them to let them follow the budget.")
    b = _broker(s)
    trades = b.closed_trades()
    deployed = sum(p.qty * p.avg_price for p in b.get_positions())
    net = sum(t["pnl_net"] for t in trades)
    wins = sum(1 for t in trades if t["pnl_net"] > 0)
    print("Paper performance:")
    print(f"  funded ₹{b.funded():,.2f} | cash ₹{b.cash():,.2f} | in positions ₹{deployed:,.2f} (at cost)")
    if trades:
        print(f"  {len(trades)} closed trades | net ₹{net:,.2f} after charges ({net / b.funded():+.2%} of budget) | "
              f"won {wins}/{len(trades)}")
    else:
        print("  no closed trades yet")
    print("Change the budget on evidence: 30+ closed trades and positive net after charges (`review`), "
          "not a few wins or losses. Every limit above re-scales with it.")
    return 0


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
        p = get_strategy(s.strategy).evaluate(df, sym, src)
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
        rt = runtime_check()
        print(("CLAUDE SEND PATH: AVAILABLE (Claude Code + guard hook: " + rt.hook_source + ")") if rt.ok else
              "CLAUDE SEND PATH: UNAVAILABLE — approve with --send-via app and place orders yourself in Groww")
        for why in rt.problems:
            print("  -", why)
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
                  f"`live approve {r.ticket['intent_id']} --reply \"<their words>\" --send-via claude|app`. "
                  f"A Claude send must happen within {s.live_approval_ttl_seconds}s.")
        return 0 if r.ok else 1
    try:
        if args.lcmd == "approve":
            reply = args.reply
            if reply is None:
                try:
                    reply = input("Type 'yes' to approve this REAL-MONEY order (anything else declines): ").strip()
                except EOFError:
                    reply = ""
            if args.send_via == "claude":
                rt = runtime_check()
                if not rt.ok:
                    print("REFUSED: Claude cannot send this order safely from here:")
                    for why in rt.problems:
                        print("  -", why)
                    print("Approve with --send-via app and place it yourself in the Groww app instead.")
                    return 2
            t = desk.ledger.approve(args.intent_id, reply, datetime.now(IST), via=args.send_via)
            journal.record("APPROVED", "live", f"reply: {reply[:60]} (send via {args.send_via})",
                           symbol=t["symbol"], intent_id=t["intent_id"])
            head = f"APPROVED {t['side']} {t['qty']} {t['symbol']} @ ₹{t['limit_price']} LIMIT"
            if args.send_via == "claude":
                print(f"{head} for {s.live_approval_ttl_seconds}s. Send exactly this order through the Groww "
                      "order tool; the guard hook will ask the user to confirm it.")
            else:
                print(f"{head}. YOU place exactly this order in the Groww app now (LIMIT, not market). The guard "
                      f"will not let Claude send it. Then: live record {t['intent_id']} --status ... "
                      "--order-id ... --filled-qty ... --avg-price ...")
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
    if args.universe:
        symbols = _universe(args.universe, s)
    if any(sym.startswith("SYNTH_") for sym in symbols):
        print("SYNTH_* are synthetic sample symbols, not NSE listings. Give real NSE symbols, e.g. INFY TCS.")
        return 2
    # --indices/--etf alone fetch only those; with symbols or --universe the stocks come too
    jobs = [] if (args.indices or args.etf) and not (args.symbols or args.universe) else [(symbols, args.out)]
    if args.indices:
        jobs.append((list(INDICES), s.indices_dir))
    if args.etf:
        jobs.append((ETF_SYMBOLS, s.etf_dir))
    bad = 0
    for syms, out in jobs:
        print(f"Downloading {len(syms)} NSE symbol(s) from {YAHOO_SOURCE}, {args.years}y daily, into {out} ...")
        for sym, status, msgs in fetch_to_csv(syms, out, args.years, cal):
            bad += status != "OK"
            print(f"  {sym:12} {status:7} {msgs[0] if msgs else ''}")
            for m in msgs[1:]:
                print(f"  {'':12} warning: {m}")
    print("Unofficial free data for personal research; re-run after 18:00 IST for the latest close.")
    return 1 if bad else 0




# ---------------------------------------------------------------- research commands (v0.3)
ETF_SYMBOLS = ["NIFTYBEES", "JUNIORBEES", "BANKBEES", "GOLDBEES"]


def _universe(name: str, s: Settings | None = None) -> list[str]:
    """A named list from config/universes.yaml, or an official index list
    downloaded with `universe-fetch` (e.g. NIFTY500)."""
    import yaml
    from .market_data import index_lists
    data = yaml.safe_load(config_file("universes.yaml").read_text(encoding="utf-8")) or {}
    u = (data.get("universes") or {})
    if name in u:
        return [str(x).upper() for x in u[name]["symbols"]]
    folder = s.universes_dir if s is not None else "data/universes"
    df = index_lists.load(name, folder)
    if df is not None:
        return [str(x).upper() for x in df["Symbol"]]
    raise KeyError(f"unknown universe {name!r}: not in config/universes.yaml ({', '.join(u)}) and no "
                   f"{folder}/{name.upper()}.csv — download it with `universe-fetch {name.upper()}`")


def _sector_map(s: Settings) -> dict[str, dict]:
    """Official NSE industries from downloaded index lists win over the approximate config/sectors.yaml."""
    from .analysis.sectors import load_sector_map
    from .market_data import index_lists
    return {**load_sector_map(config_file("sectors.yaml")), **index_lists.official_sector_map(s.universes_dir)}


def cmd_universe_fetch(args):
    from .market_data import index_lists
    s, _, _ = _ctx(args)
    names = [n.upper() for n in args.names] or ["NIFTY500"]
    bad = 0
    for n in names:
        try:
            p, df = index_lists.fetch(n, s.universes_dir)
        except DataError as e:
            print(f"  {n:16} ERROR {e}")
            bad += 1
            continue
        series = ", ".join(f"{k} {v}" for k, v in df["Series"].value_counts().items())
        print(f"  {n:16} OK {len(df)} stocks ({series}) → {p}  [{index_lists.BASE.format(file=index_lists.LISTS[n])}]")
    print("Official NSE Indices lists; constituents change at each review. Next: "
          f"`data-fetch --universe {names[0]}` (about 1 second per stock).")
    return 1 if bad else 0


def _frames(s: Settings, cal, data_dir: str | None = None, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Valid CSVs from a folder (all, or the given symbols). Invalid files are skipped with a note."""
    base = Path(data_dir or s.data_dir)
    files = [base / f"{x}.csv" for x in symbols] if symbols else sorted(base.glob("*.csv"))
    out = {}
    for f in files:
        try:
            df, rep, _ = load_csv(f, f.stem, cal)
        except DataError as e:
            print(f"  skipped {f.stem}: {e}", file=sys.stderr)
            continue
        if rep.ok:
            out[f.stem.upper()] = df
        else:
            print(f"  skipped {f.stem}: {'; '.join(rep.errors)}", file=sys.stderr)
    return out


def _index(s: Settings, name: str, required: bool = True) -> pd.DataFrame | None:
    p = Path(s.indices_dir) / f"{name}.csv"
    if not p.exists():
        if required:
            raise DataError(f"no {name} data at {p}; run `data-fetch --indices`")
        return None
    df, rep, _ = load_csv(p, name)
    if not rep.ok:
        raise DataError(f"{p}: " + "; ".join(rep.errors))
    return df


def _as_of(args):
    return pd.Timestamp(args.as_of).date() if getattr(args, "as_of", None) else None


def _symbols_arg(args) -> list[str] | None:
    if getattr(args, "symbols", None):
        return [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    if getattr(args, "universe", None):
        return _universe(args.universe, load_settings(args.config))
    return None


def cmd_strategies(args):
    from .workflows.allocation import ALLOCATION_STRATEGIES
    s, _, _ = _ctx(args)
    print(f"SIGNAL STRATEGIES (per stock; used by analyze/scan/backtest/autopilot/live). Active: {s.strategy}")
    for st in SIGNAL_STRATEGIES.values():
        print(f"  {st.name} v{st.version}: {st.summary}\n      exits: {st.exit.describe()}\n      idea: {st.origin}")
    print("ALLOCATION STRATEGIES (portfolio, monthly; used by `allocate` and `lab`):")
    for k, v in ALLOCATION_STRATEGIES.items():
        print(f"  {k}: {v}")
    print("Lab results on real NSE data: docs/STRATEGY_LAB.md. Run `lab` to re-test on your data.")
    return 0


def cmd_lab(args):
    from .backtesting.lab import LAB_STRATEGIES, format_lab, run_lab
    from .backtesting.portfolio import LabConfig
    s, cal, _ = _ctx(args)
    frames = _frames(s, cal, args.data_dir, _symbols_arg(args))
    if len(frames) < 2:
        print(f"Need at least 2 valid stock CSVs in {args.data_dir or s.data_dir} (run data-fetch).")
        return 1
    nifty = _index(s, "NIFTY50")
    etf_path = Path(s.etf_dir) / "NIFTYBEES.csv"
    etf = None
    if etf_path.exists():
        df, rep, _ = load_csv(etf_path, "NIFTYBEES")
        etf = {"NIFTYBEES": df} if rep.ok else None
    names = [x.strip() for x in args.strategies.split(",")] if args.strategies else list(LAB_STRATEGIES)
    if args.gate:
        names += [f"{n}+gate" for n in names if n in SIGNAL_STRATEGIES]
    first = max(df["date"].iloc[0] for df in frames.values()) + pd.Timedelta(days=380)   # indicator warm-up
    start = pd.Timestamp(args.start).date() if args.start else first.date()
    end = pd.Timestamp(args.end).date() if args.end else min(df["date"].iloc[-1] for df in frames.values()).date()
    split = pd.Timestamp(args.split).date() if args.split else (pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2).date()
    cfg = LabConfig(capital=args.capital, max_positions=args.max_positions, risk_pct=args.risk_pct / 100,
                    max_position_pct=1 / args.max_positions, slippage_bps=s.slippage_bps, start=start, end=end,
                    product=s.product, charges=s.charges)
    rows, verdicts = run_lab(frames, nifty, etf, names, cfg, split)
    hdr = (f"STRATEGY LAB — {len(frames)} stocks, {start} → {end}, split {split}, study capital ₹{args.capital:,.0f} "
           f"(PAPER research), max {args.max_positions} positions, Groww charges + {s.slippage_bps:g} bps slippage")
    print(format_lab(rows, verdicts, hdr))
    return 0


def cmd_regime(args):
    from .analysis.regime import compute, format_regime
    s, cal, _ = _ctx(args)
    r = compute(_index(s, "NIFTY50"), _index(s, "INDIAVIX", required=False),
                _frames(s, cal, args.data_dir, _symbols_arg(args)), _as_of(args))
    print(format_regime(r))
    return 0


def cmd_sectors(args):
    from .analysis.sectors import format_sectors, rank
    s, _, _ = _ctx(args)
    nifty = _index(s, "NIFTY50")
    secs = {n: d for n in SECTOR_INDICES if (d := _index(s, n, required=False)) is not None}
    if not secs:
        print("No sector index data; run `data-fetch --indices`.")
        return 1
    rows = rank(secs, nifty, _as_of(args))
    print(format_sectors(rows, str((_as_of(args) or nifty["date"].iloc[-1].date()))))
    return 0


def cmd_screen(args):
    from .analysis.screener import format_screen, screen
    from .analysis.sectors import load_sector_map
    s, cal, _ = _ctx(args)
    frames = _frames(s, cal, args.data_dir, _symbols_arg(args))
    if not frames:
        print(f"No valid CSVs in {args.data_dir or s.data_dir}.")
        return 1
    rows = screen(frames, _as_of(args), _sector_map(s))
    print(format_screen(rows, args.setup, args.min_rs, args.top))
    return 0


def cmd_technical(args):
    from .analysis.sectors import load_sector_map
    from .analysis.technical import analyse, format_tech
    s, cal, _ = _ctx(args)
    sym = args.symbol.upper()
    df, rep, src = load_csv(_data_path(s, args, sym), sym, cal)
    if not rep.ok:
        print("INVALID DATA:", rep.errors)
        return 2
    info = _sector_map(s).get(sym, {})
    sector_df = _index(s, info["index"], required=False) if info.get("index") else None
    t = analyse(df, sym, src, _index(s, "NIFTY50", required=False), sector_df, info.get("sector", ""),
                load_events(Path(args.data_dir or s.data_dir), sym), _as_of(args))
    print(format_tech(t))
    return 0


def cmd_size(args):
    from .analysis.planner import size
    s, _, _ = _ctx(args)
    risk = args.risk if args.risk is not None else s.max_risk_per_trade_inr
    budget = args.budget if args.budget is not None else min(s.max_single_order_value_inr, s.max_experimental_allocation_inr)
    z = size(args.entry, args.stop, risk, budget, s, args.target)
    print(f"POSITION SIZE (long, whole shares, Groww {s.product} charges) entry ₹{args.entry:,.2f} stop ₹{args.stop:,.2f}")
    print(f"  risk limit ₹{risk:,.2f} | budget ₹{budget:,.2f} → {z.qty} shares = ₹{z.value:,.2f} (limited by {z.limited_by})")
    print(f"  loss at stop incl. charges ₹{z.loss_at_stop:,.2f} | buy charges ₹{z.buy_costs:.2f} | round trip ≈ ₹{z.roundtrip_costs:.2f}")
    for n in z.notes:
        print("  note:", n)
    return 0 if z.qty else 1


def cmd_plan(args):
    from .analysis.planner import format_plan, plan
    s, cal, _ = _ctx(args)
    sym = args.symbol.upper()
    strat = get_strategy(s.strategy)
    df, rep, src = load_csv(_data_path(s, args, sym), sym, cal)
    if not rep.ok:
        print("INVALID DATA:", rep.errors)
        return 2
    if args.as_of:
        df = df[df["date"].dt.date <= _as_of(args)].reset_index(drop=True)
    levels = (args.entry, args.stop, args.target)
    if None in levels:
        if any(v is not None for v in levels):
            print("Give all of --entry, --stop and --target, or none (then the strategy's plan is used).")
            return 2
        p = strat.evaluate(df, sym, src)
        if p.decision != "TRADE":
            print(f"{sym}: {strat.name} says NO_TRADE as of {p.as_of:%Y-%m-%d}: {'; '.join(p.reasons)[:200]}")
            print("Pass --entry --stop --target to plan your own levels.")
            return 1
        levels = (p.entry, p.stop, p.target)
    pl = plan(sym, *levels, s, strat.exit, strat.name if args.entry is None else "manual", args.risk, args.budget)
    print(format_plan(pl))
    print(f"  data {src} as of {df['date'].iloc[-1].date()} | limits from settings: risk ₹{s.max_risk_per_trade_inr}, "
          f"order cap ₹{s.max_single_order_value_inr}, capital floor {s.capital_floor_pct:g}%")
    if args.odds and pl.size.qty:
        r = simulate(df, sym, pl.entry, pl.stop, pl.target, s, qty=pl.size.qty, max_hold_days=min(strat.exit.max_hold_days, 20),
                     paths=5000, data_source=src)
        print("\n" + format_result(r))
    return 0


def cmd_exit_plan(args):
    from .analysis.planner import exit_plan
    from .indicators.core import add_indicators
    s, cal, _ = _ctx(args)
    b = _broker(s)
    strat = get_strategy(s.strategy)
    pos = b.get_positions()
    print(PAPER_BANNER)
    if not pos:
        print("No open paper positions.")
        return 0
    for p in pos:
        try:
            df, rep, _ = load_csv(_data_path(s, args, p.symbol), p.symbol, cal)
        except DataError as e:
            print(f"  {p.symbol}: {e}")
            continue
        x = add_indicators(df.iloc[-300:].reset_index(drop=True))
        e = exit_plan(p.symbol, p.qty, p.avg_price, p.stop or 0.0, p.target, p.opened_at.date().isoformat(), x, strat.exit)
        print(f"  {e['symbol']} {e['qty']} @ ₹{e['avg']} → ₹{e['close']} ({e['r_now']:+.2f}R, ₹{e['open_pnl']:+,.2f}) | "
              f"stop ₹{e['stop']} → effective ₹{e['effective_stop']}{' (raise it)' if e['raise_stop'] else ''} | "
              f"{e['dist_to_stop_pct']}% above stop | close rule: {e['close_rule']} | "
              f"held {e['held_bars']}/{e['max_hold']} bars{' — TIME EXIT DUE' if e['time_exit_due'] else ''}")
    print(f"  Exit rules ({strat.name}): {strat.exit.describe()}. The autopilot applies them on its next tick.")
    return 0


def cmd_portfolio(args):
    from .analysis.portfolio import Holding, format_portfolio, load_holdings, review
    from .analysis.sectors import load_sector_map
    s, cal, _ = _ctx(args)
    if args.holdings:
        holdings, source = load_holdings(args.holdings), f"file {args.holdings}"
    else:
        holdings = [Holding(p.symbol, p.qty, p.avg_price, p.stop) for p in _broker(s).get_positions()]
        source = "paper account"
    if not holdings:
        print(f"No holdings in the {source}. Pass --holdings FILE (CSV/JSON exported or read from Groww).")
        return 1
    syms = [h.symbol for h in holdings]
    base = Path(args.data_dir or s.data_dir)
    frames = _frames(s, cal, str(base), [x for x in syms if (base / f"{x}.csv").exists()])
    prices = {k: q.price for k, q in _parse_prices(args.prices, args.price_source).items()} if args.prices else None
    events = {x: load_events(base, x) for x in syms}
    print(format_portfolio(review(holdings, frames, _sector_map(s), prices, events),
                           source + (f", prices {args.price_source}" if args.prices else ", prices = last close in data")))
    return 0


def cmd_alerts(args):
    from .analysis.alerts import evaluate, format_alerts, load_rules
    s, cal, _ = _ctx(args)
    rules = load_rules(args.file)
    positions = _broker(s).get_positions()
    syms = sorted({str(r["symbol"]).upper() for r in rules} | {p.symbol for p in positions})
    base = Path(args.data_dir or s.data_dir)
    frames = _frames(s, cal, str(base), [x for x in syms if (base / f"{x}.csv").exists()])
    prices = {k: q.price for k, q in _parse_prices(args.prices, args.price_source).items()} if args.prices else None
    if not rules and not positions:
        print(f"No alert rules in {args.file} and no paper positions. See config/alerts.example.yaml.")
        return 0
    as_of = max((df["date"].iloc[-1].date() for df in frames.values()), default="-")
    print(format_alerts(evaluate(rules, frames, prices, positions), f"{as_of}" + (" + current prices" if prices else "")))
    return 0


def cmd_actions(args):
    from .analysis.actions import format_actions, summarise
    s, cal, _ = _ctx(args)
    base = Path(args.data_dir or s.data_dir)
    syms = [x.upper() for x in args.symbols] or sorted(p.stem for p in (base / "events").glob("*.json"))
    rows = []
    for sym in syms:
        ev = load_events(base, sym)
        try:
            df, _, _ = load_csv(base / f"{sym}.csv", sym)
        except DataError:
            print(f"  {sym}: no price data in {base}", file=sys.stderr)
            continue
        rows.append(summarise(sym, df, ev))
    if not rows:
        print(f"No corporate-action data in {base}/events (run data-fetch).")
        return 1
    print(format_actions(rows))
    return 0


def cmd_allocate(args):
    from .workflows.allocation import AllocationPilot, format_view, targets
    s, cal, journal = _ctx(args)
    nifty = _index(s, "NIFTY50")
    if args.strategy_name == "etf_trend":
        frames = _frames(s, cal, s.etf_dir, [args.etf])
    else:
        frames = _frames(s, cal, args.data_dir, _symbols_arg(args) or list(s.watchlist))
    if not frames:
        print("No data for this allocation (run data-fetch --etf / data-fetch).")
        return 1
    pilot = AllocationPilot(s, journal)
    view = targets(args.strategy_name, nifty, frames, set(pilot.held()), etf=args.etf)
    print(PAPER_BANNER)
    print(format_view(view, pilot.held()))
    if not args.paper:
        print("  (view only; add --paper to rebalance the separate allocation PAPER account)")
        return 0
    if not view.is_month_end and not args.force:
        print(f"  Not a rebalance day; the rule checks at month end ({view.next_check}). Use --force to rebalance now.")
        return 0
    if args.prices:
        quotes, now = _parse_prices(args.prices, args.price_source), datetime.now(IST)
    else:
        last = {sym: df for sym, df in frames.items()}
        d = max(df["date"].iloc[-1].date() for df in last.values())
        now = datetime.combine(d, time(15, 20), tzinfo=IST)
        quotes = {sym: Quote(symbol=sym, price=float(df["close"].iloc[-1]), timestamp=now,
                             source="replay:last-close (NOT live)") for sym, df in last.items()}
        print(f"  REPLAY rebalance at the {d} closes — not live prices.")
    for line in pilot.rebalance(view, quotes, now):
        print("  " + line)
    print(f"  Allocation paper cash ₹{pilot.broker.cash():,.2f}; holdings {pilot.held() or 'none'}")
    return 0


def cmd_daily(args):
    """The routine (tradermonty workflows, day-trader morning flow) in one command."""
    import contextlib
    import io
    s, cal, _ = _ctx(args)
    steps = []
    if args.fetch:
        steps.append(("Refresh data", ["data-fetch", "--indices", "--etf"]))
        steps.append(("Refresh watchlist", ["data-fetch"]))
    steps += [("Market regime", ["regime"]), ("Sector rotation", ["sectors"]),
              ("Watchlist screen", ["screen", "--symbols", ",".join(s.watchlist)]),
              ("Allocation check (etf_trend)", ["allocate", "--strategy-name", "etf_trend"]),
              ("Alerts", ["alerts"]), ("Open paper positions", ["exit-plan"])]
    if args.paper:
        steps.append(("Paper autopilot tick (last closes)", ["autopilot"]))
    steps.append(("Risk status", ["risk-status"]))
    out = [f"# Daily routine {datetime.now(IST):%Y-%m-%d %H:%M} IST (paper; research, not advice)"]
    for title, argv in steps:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                main(["--config", args.config] + argv
                     + (["--strategy", args.strategy] if args.strategy and argv[0] in ("autopilot", "exit-plan") else []))
            except Exception as e:                 # one failed step does not stop the routine
                print(f"step failed: {type(e).__name__}: {e}")
        out += [f"\n## {title}", "```", buf.getvalue().rstrip(), "```"]
    text = "\n".join(out)
    print(text)
    if args.out:
        d = Path(args.out)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{datetime.now(IST):%Y-%m-%d}.md"
        f.write_text(text, encoding="utf-8")
        print(f"\nsaved {f}")
    return 0


def cmd_doctor(args):
    """Environment and setup check, with the next step for anything missing."""
    import importlib
    import platform
    s, cal, _ = _ctx(args)
    ok, todo = [], []
    ok.append(f"Python {platform.python_version()} ({sys.executable})")
    for mod in ("pandas", "numpy", "pydantic", "yaml"):
        try:
            m = importlib.import_module(mod)
            ok.append(f"{mod} {getattr(m, '__version__', '')}")
        except ImportError:
            todo.append(f"install {mod}: python \"{PLUGIN_ROOT / 'scripts' / 'india.py'}\" --setup")
    ok.append(f"plugin folder {PLUGIN_ROOT}")
    ok.append(f"project folder {Path.cwd()}")
    (ok if Path(args.config).exists() else todo).append(
        f"settings {args.config}" if Path(args.config).exists() else
        f"no {args.config}: built-in safe defaults in use (copy config/settings.example.yaml to customise)")
    ok.append(f"strategy {s.strategy} | budget ₹{s.max_experimental_allocation_inr:g} | risk/trade ₹{s.max_risk_per_trade_inr:g} "
              f"| capital floor {s.capital_floor_pct:g}% (₹{s.capital_floor:g}) | mode {s.trading_mode}")
    data = Path(s.data_dir)
    n = len(list(data.glob("*.csv"))) if data.exists() else 0
    if n and not any(p.name.startswith("SYNTH_") for p in data.glob("*.csv")):
        ok.append(f"{n} stock CSVs in {data}")
    else:
        todo.append(f"real data: data-fetch (watchlist) — {data} has {n} files"
                    + (" (SYNTHETIC sample)" if n else ""))
    for name, folder in (("indices", s.indices_dir), ("ETFs", s.etf_dir)):
        k = len(list(Path(folder).glob("*.csv"))) if Path(folder).exists() else 0
        (ok if k else todo).append(f"{k} {name} CSVs in {folder}" if k else f"{name}: data-fetch --{'indices' if name == 'indices' else 'etf'}")
    year = datetime.now(IST).year
    (ok if cal.covers(year) else todo).append(
        f"NSE holidays for {year} listed" if cal.covers(year) else
        f"NSE holidays for {year} missing: fill config/nse_holidays.yaml from the official NSE circular")
    tools = load_tools()
    (ok if tools["read_only"] or tools["order_tools"] else todo).append(
        f"Groww tools classified: {len(tools['read_only'])} read-only, {len(tools['order_tools'])} order" if tools["read_only"] or tools["order_tools"]
        else "Groww tools not classified yet: connect Groww, list its tools, fill config/groww_tools.yaml (orders stay denied until then)")
    hook = Path(".claude/settings.json")
    plugin_hook = PLUGIN_ROOT / "hooks" / "hooks.json"
    ok.append("guard hook: " + ", ".join(x for x, y in (("project .claude/settings.json", hook.exists()),
                                                        ("plugin hooks/hooks.json", plugin_hook.exists())) if y) or "none")
    print("DOCTOR — india-trading-skill")
    for x in ok:
        print(f"  ✓ {x}")
    for x in todo:
        print(f"  ✗ {x}")
    if not todo:
        print("  nothing to do")
    return 0 if not todo else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="india_trading", description="NSE research + paper-trading toolkit (no live orders).")
    ap.add_argument("--config", default="config/settings.yaml", help="YAML settings (optional)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    strategy_help = f"signal strategy ({', '.join(SIGNAL_STRATEGIES)}); default from settings"

    sub.add_parser("status", help="show mode, limits and NSE session").set_defaults(fn=cmd_status)
    sub.add_parser("market-check", help="NSE session status").set_defaults(fn=cmd_market_check)
    p = sub.add_parser("scan", help="run the strategy on every CSV in the data dir")
    p.add_argument("--data-dir"); p.add_argument("--strategy", help=strategy_help); p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("analyze", help="analyse one symbol from its CSV (no orders)")
    p.add_argument("symbol"); p.add_argument("--data-dir"); p.add_argument("--strategy", help=strategy_help)
    p.add_argument("--as-of", help="historical replay: use only bars up to this date (YYYY-MM-DD)")
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("backtest", help="backtest a signal strategy on one CSV (single stock)")
    p.add_argument("symbol"); p.add_argument("--data-dir"); p.add_argument("--strategy", help=strategy_help); p.add_argument("--capital", type=float)
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
        q.add_argument("--strategy", help=strategy_help)
        if name == "start":
            q.add_argument("--approve", help="non-interactive approval text for PAPER orders, e.g. yes")
        q.set_defaults(fn=fn)
    psub.add_parser("status", help="paper cash, positions, closed trades").set_defaults(fn=cmd_paper_status)

    p = sub.add_parser("journal", help="show or export the journal")
    p.add_argument("--mode", choices=["paper", "live", "backtest"]); p.add_argument("--limit", type=int, default=30)
    p.add_argument("--export", help="CSV path"); p.set_defaults(fn=cmd_journal)
    sub.add_parser("risk-status", help="limits and today's usage").set_defaults(fn=cmd_risk_status)
    p = sub.add_parser("budget", help="show the budget, the limits that scale with it and paper performance; "
                                      "`budget set N` invests more or less")
    p.add_argument("action", nargs="?", choices=["show", "set"], default="show")
    p.add_argument("amount", nargs="?", type=float, help="new budget in ₹ (with `set`)")
    p.set_defaults(fn=cmd_budget)
    p = sub.add_parser("kill-switch", help="block all new orders (on) or allow them again (off)")
    p.add_argument("state", choices=["on", "off"]); p.add_argument("--reason"); p.set_defaults(fn=cmd_kill)
    p = sub.add_parser("monitor", help="read-only polling monitor")
    p.add_argument("action", choices=["start", "stop"]); p.add_argument("--interval", type=int, default=300)
    p.add_argument("--ticks", type=int, help="stop after N ticks"); p.add_argument("--data-dir")
    p.set_defaults(fn=cmd_monitor)
    p = sub.add_parser("timemachine", help="Monte-Carlo odds of one long plan (stop vs target) from the stock's own daily bars")
    p.add_argument("symbol"); p.add_argument("--data-dir"); p.add_argument("--strategy", help=strategy_help); p.add_argument("--as-of")
    p.add_argument("--entry", type=float); p.add_argument("--stop", type=float); p.add_argument("--target", type=float)
    p.add_argument("--qty", type=int, help="default: what the risk manager would size")
    p.add_argument("--hold", type=int, default=ma_trend.PARAMS.max_hold_days, help="max hold days to simulate")
    p.add_argument("--paths", type=int, default=10_000); p.add_argument("--lookback", type=int, default=250)
    p.add_argument("--seed", type=int, default=19); p.set_defaults(fn=cmd_timemachine)
    p = sub.add_parser("autopilot", help="one unattended PAPER tick: manage exits, then auto-approved paper entries")
    p.add_argument("--data-dir"); p.add_argument("--strategy", help=strategy_help)
    p.add_argument("--prices", help="current prices, e.g. INFY=1520.5,TCS=3901 (omit for a replay tick at the last close)")
    p.add_argument("--price-source", default="user-entered", help="where --prices came from, e.g. groww-mcp")
    p.set_defaults(fn=cmd_autopilot)
    p = sub.add_parser("replay", help="run the paper autopilot day by day over past data (separate state)")
    p.add_argument("--data-dir"); p.add_argument("--strategy", help=strategy_help); p.add_argument("--start"); p.add_argument("--end")
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
    p.add_argument("--years", type=int, default=10); p.add_argument("--out", default="data/real")
    p.add_argument("--universe", help="config/universes.yaml name or a downloaded index list, e.g. NIFTY500")
    p.add_argument("--indices", action="store_true", help="also fetch Nifty 50, India VIX and sector indices")
    p.add_argument("--etf", action="store_true", help="also fetch index ETFs (NIFTYBEES, JUNIORBEES, BANKBEES, GOLDBEES)")
    p.set_defaults(fn=cmd_data_fetch)
    live = sub.add_parser("live", help="REAL-MONEY desk (locked until graduation + live switches); never sends orders itself")
    lsub = live.add_subparsers(dest="lcmd", required=True)
    q = lsub.add_parser("status", help="switches, graduation test, classified Groww tools, live positions")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("tickets", help="live tickets and their states"); q.add_argument("--limit", type=int, default=30)
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("prepare", help="analyse + risk-check + write a live BUY ticket (needs graduation)")
    q.add_argument("symbol"); q.add_argument("--price", type=float, required=True)
    q.add_argument("--strategy", help=strategy_help)
    q.add_argument("--price-source", required=True, help="e.g. groww-mcp (read just now)")
    q.add_argument("--cash", type=float, help="available cash read from Groww just now (required to pass)")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("exit", help="write a live SELL ticket for a live-ledger position")
    q.add_argument("symbol"); q.add_argument("--price", type=float, required=True)
    q.add_argument("--price-source", required=True); q.add_argument("--reason", default="manual")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("approve", help="explicit per-order yes for one PREPARED ticket")
    q.add_argument("intent_id"); q.add_argument("--reply", help="only the user's own words for THIS ticket")
    q.add_argument("--send-via", required=True, choices=["claude", "app"],
                   help="claude: Claude sends it via the Groww tool (Claude Code + guard hook only); "
                        "app: you place it yourself in the Groww app")
    q.add_argument("--data-dir"); q.set_defaults(fn=cmd_live)
    q = lsub.add_parser("record", help="record the Groww result of a SENT or app-placed ticket")
    q.add_argument("intent_id"); q.add_argument("--status", required=True,
                                                choices=["FILLED", "PARTIALLY_FILLED", "REJECTED", "CANCELLED", "UNKNOWN"])
    q.add_argument("--order-id"); q.add_argument("--filled-qty", type=int, default=0)
    q.add_argument("--avg-price", type=float); q.add_argument("--note"); q.add_argument("--data-dir")
    q.set_defaults(fn=cmd_live)

    # ---- v0.3 research commands
    sub.add_parser("strategies", help="list signal and allocation strategies with their rules").set_defaults(fn=cmd_strategies)
    p = sub.add_parser("lab", help="portfolio strategy lab vs Nifty and buy & hold, earlier/later halves (PAPER research)")
    p.add_argument("--strategies", help="comma list (default: all)"); p.add_argument("--data-dir")
    p.add_argument("--symbols", help="comma list (default: every CSV in the data dir)"); p.add_argument("--universe")
    p.add_argument("--start"); p.add_argument("--end"); p.add_argument("--split", help="date dividing the halves")
    p.add_argument("--capital", type=float, default=100_000); p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--risk-pct", type=float, default=1.0, help="%% of equity risked per signal trade")
    p.add_argument("--gate", action="store_true", help="also run each signal strategy with the Nifty 50 market gate")
    p.set_defaults(fn=cmd_lab)
    p = sub.add_parser("regime", help="NSE market regime: Nifty trend filter, distribution days, FTD, India VIX, breadth")
    p.add_argument("--as-of"); p.add_argument("--data-dir"); p.add_argument("--symbols"); p.add_argument("--universe")
    p.set_defaults(fn=cmd_regime)
    p = sub.add_parser("sectors", help="NSE sector indices ranked by relative strength vs Nifty 50")
    p.add_argument("--as-of"); p.set_defaults(fn=cmd_sectors)
    p = sub.add_parser("screen", help="multi-setup screener with RS rating and stage over a universe")
    p.add_argument("--setup", help="only rows with this setup, e.g. donchian_trend, near_high, momentum_burst")
    p.add_argument("--min-rs", type=int, default=0); p.add_argument("--top", type=int, default=30)
    p.add_argument("--as-of"); p.add_argument("--data-dir"); p.add_argument("--symbols"); p.add_argument("--universe")
    p.set_defaults(fn=cmd_screen)
    p = sub.add_parser("technical", help="one-stock technical report (trend, levels, RS vs Nifty/sector, strategies)")
    p.add_argument("symbol"); p.add_argument("--as-of"); p.add_argument("--data-dir"); p.set_defaults(fn=cmd_technical)
    p = sub.add_parser("size", help="whole-share position size with loss at stop incl. charges")
    p.add_argument("entry", type=float); p.add_argument("stop", type=float); p.add_argument("--target", type=float)
    p.add_argument("--risk", type=float, help="₹ you accept to lose (default: settings)")
    p.add_argument("--budget", type=float, help="₹ for this position (default: settings order cap)")
    p.set_defaults(fn=cmd_size)
    p = sub.add_parser("plan", help="full trade plan: levels, R-multiples, size, charges, break-even, exits (+ odds)")
    p.add_argument("symbol"); p.add_argument("--strategy", help=strategy_help)
    p.add_argument("--entry", type=float); p.add_argument("--stop", type=float); p.add_argument("--target", type=float)
    p.add_argument("--risk", type=float); p.add_argument("--budget", type=float); p.add_argument("--as-of")
    p.add_argument("--odds", action="store_true", help="add time-machine odds"); p.add_argument("--data-dir")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("exit-plan", help="open paper positions: trailing stop, close rule, time exit, R now")
    p.add_argument("--strategy", help=strategy_help); p.add_argument("--data-dir"); p.set_defaults(fn=cmd_exit_plan)
    p = sub.add_parser("portfolio", help="holdings review: weights, sectors, correlation, review triggers (no selling)")
    p.add_argument("--holdings", help="CSV/JSON of symbol,qty,avg_price (e.g. read from Groww); default: paper account")
    p.add_argument("--prices", help="current prices SYM=PX,..."); p.add_argument("--price-source", default="user-entered")
    p.add_argument("--data-dir"); p.set_defaults(fn=cmd_portfolio)
    p = sub.add_parser("alerts", help="check price/setup alert rules and paper-position alerts (no orders)")
    p.add_argument("--file", default="config/alerts.yaml"); p.add_argument("--prices")
    p.add_argument("--price-source", default="user-entered"); p.add_argument("--data-dir"); p.set_defaults(fn=cmd_alerts)
    p = sub.add_parser("actions", help="dividends and splits from the fetched data (past ex-dates)")
    p.add_argument("symbols", nargs="*"); p.add_argument("--data-dir"); p.set_defaults(fn=cmd_actions)
    p = sub.add_parser("allocate", help="monthly allocation strategies: today's targets; --paper rebalances a PAPER account")
    p.add_argument("--strategy-name", default="etf_trend", choices=["etf_trend", "trend_filtered_core", "momentum_rotation"])
    p.add_argument("--etf", default="NIFTYBEES"); p.add_argument("--paper", action="store_true")
    p.add_argument("--force", action="store_true", help="rebalance even if today is not month end")
    p.add_argument("--prices"); p.add_argument("--price-source", default="user-entered")
    p.add_argument("--data-dir"); p.add_argument("--symbols"); p.add_argument("--universe"); p.set_defaults(fn=cmd_allocate)
    p = sub.add_parser("daily", help="daily routine: regime, sectors, screen, allocation, alerts, positions (+ paper tick)")
    p.add_argument("--fetch", action="store_true", help="refresh data first (internet)")
    p.add_argument("--paper", action="store_true", help="also run one paper autopilot tick at the last closes")
    p.add_argument("--strategy", help=strategy_help); p.add_argument("--out", default="reports/daily")
    p.set_defaults(fn=cmd_daily)
    sub.add_parser("doctor", help="check the installation, data and setup; prints what to do next").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("universe-fetch", help="download official NSE index lists (NIFTY50/100/200/500, MIDCAP150, ...)")
    p.add_argument("names", nargs="*", help="e.g. NIFTY500 NIFTY50 (default NIFTY500)")
    p.set_defaults(fn=cmd_universe_fetch)
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
    except (KeyError, ValueError) as e:
        print("ERROR:", e.args[0] if e.args else e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
