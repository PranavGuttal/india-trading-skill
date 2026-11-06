"""Graduation test: the evidence required before ANY live order can be prepared.

Computed from the forward PAPER account (state/paper.db) and its journal,
never from backtests or replays. Every paper entry must have been decided on
non-synthetic data with a manually supplied (live-read) price; one synthetic
or replay entry anywhere in the paper account fails graduation until the
account is reset. A typed price is not trusted on its own: each paper fill
must lie inside that day's real low-high range (verify_entry_prices).
Minimums come from settings and can only be raised.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings

_TAINTED = ("synthetic", "replay")


@dataclass
class Graduation:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def check(settings: Settings, closed: list[dict], buy_intent_ids: list[str], events: list[dict],
          price_problems: list[str] | None = None) -> Graduation:
    """closed: paper closed trades; buy_intent_ids: filled paper BUY orders;
    events: paper journal events (any order); price_problems: entries whose
    typed price could not be confirmed against that day's real bar."""
    reasons = []
    approvals = {e["intent_id"]: e for e in events if e["kind"] == "RISK_APPROVED" and e.get("intent_id")}
    approved_by_user = {e["intent_id"] for e in events if e["kind"] == "APPROVED"}
    tainted, unknown = [], []
    for iid in buy_intent_ids:
        ev = approvals.get(iid)
        if ev is None:
            unknown.append(iid)
            continue
        src = f"{ev.get('data_source') or ''} {ev.get('payload') or ''}".lower()
        if any(t in src for t in _TAINTED) or "manual:" not in src:
            tainted.append(iid)
    net = round(sum(float(t["pnl_net"]) for t in closed), 2)
    days = len({t["trade_date"] for t in closed})
    stats = {"closed_trades": len(closed), "net_pnl": net, "distinct_days": days,
             "tainted_entries": len(tainted), "entries_without_record": len(unknown),
             "unconfirmed_prices": len(price_problems or [])}
    if len(closed) < settings.graduation_min_trades:
        reasons.append(f"only {len(closed)} closed paper trades (need {settings.graduation_min_trades})")
    if days < settings.graduation_min_days:
        reasons.append(f"trades on only {days} distinct days (need {settings.graduation_min_days})")
    if net <= 0:
        reasons.append(f"paper net P&L after charges is ₹{net} (must be positive)")
    if tainted:
        reasons.append(f"{len(tainted)} paper entries used synthetic/replay data or no live-read price; "
                       "reset state/paper.db and paper trade on real data only")
    if unknown:
        reasons.append(f"{len(unknown)} paper entries have no RISK_APPROVED journal record")
    if price_problems:
        reasons.append(f"{len(price_problems)} paper entry price(s) not confirmed by that day's real NSE bar "
                       f"(e.g. {price_problems[0]}); fetch data after 18:00 IST, or the price was mistyped")
    missing_yes = [i for i in buy_intent_ids if i not in approved_by_user]
    if missing_yes:
        reasons.append(f"{len(missing_yes)} paper entries have no APPROVED journal record")
    return Graduation(passed=not reasons, reasons=reasons, stats=stats)


def format_graduation(g: Graduation) -> str:
    head = "GRADUATION: PASSED (live preparation may be unlocked by the live switches)" if g.passed else \
        "GRADUATION: NOT PASSED — live orders stay locked"
    return "\n".join([head, f"  {g.stats}"] + [f"  - {r}" for r in g.reasons])


PRICE_TOLERANCE = 0.005   # 0.5% outside the day's range covers slippage on the paper fill


def verify_entry_prices(entries: list[dict], data_dir) -> list[str]:
    """entries: dicts with symbol, trade_date (YYYY-MM-DD) and price (paper fill).
    Returns one problem string per entry whose price is not inside that day's
    real bar (or whose bar is missing). Synthetic files never confirm anything."""
    from pathlib import Path

    import pandas as pd

    problems: list[str] = []
    cache: dict[str, object] = {}
    for e in entries:
        sym, day, px = str(e["symbol"]).upper(), str(e["trade_date"]), e.get("price")
        if px is None:
            problems.append(f"{sym} {day}: no fill price")
            continue
        if sym not in cache:
            path = Path(data_dir) / f"{sym}.csv"
            try:
                df = pd.read_csv(path)
                df.columns = [c.strip().lower() for c in df.columns]
                if "source" in df.columns and df["source"].astype(str).str.contains("SYNTHETIC", case=False).any():
                    df = None
            except (OSError, ValueError):
                df = None
            cache[sym] = df
        df = cache[sym]
        if df is None:
            problems.append(f"{sym} {day}: no real data file")
            continue
        row = df[pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d") == day]
        if row.empty:
            problems.append(f"{sym} {day}: no bar for that day yet")
            continue
        lo, hi = float(row["low"].iloc[0]), float(row["high"].iloc[0])
        if not (lo * (1 - PRICE_TOLERANCE) <= float(px) <= hi * (1 + PRICE_TOLERANCE)):
            problems.append(f"{sym} {day}: ₹{float(px):.2f} outside the day's range ₹{lo:.2f}–₹{hi:.2f}")
    return problems
