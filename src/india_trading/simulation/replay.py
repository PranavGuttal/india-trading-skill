"""Day-by-day replay: run the paper autopilot over past dates as if each one
were live, with fresh state in its own folder (never touches state/paper.db).

Each trading day it ticks once at 15:20 IST using that day's close as the
price, so entries fill near the close and exits see the full day's bar. Only
data on or before the replay date is visible to the strategy.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

import pandas as pd

from ..backtesting.engine import MIN_TRADES_FOR_EVIDENCE
from ..brokers.paper_broker import PaperBroker
from ..config import Settings
from ..indicators.core import add_indicators
from ..journal.store import Journal
from ..market_data.calendar import IST, NSECalendar
from ..market_data.csv_source import load_csv
from ..models import Quote
from ..risk.manager import block_reason_key
from ..workflows.autopilot import AutoPilot, TickReport


@dataclass
class ReplayResult:
    start: str
    end: str
    days: int
    starting_cash: float
    equity: pd.Series
    trades: list[dict]
    signals: int
    blocked: int
    block_reasons: dict[str, int] = field(default_factory=dict)
    data_sources: list[str] = field(default_factory=list)
    out_dir: str = ""

    def metrics(self) -> dict:
        t = self.trades
        net = [x["pnl_net"] for x in t]
        wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
        eq = self.equity
        dd = float(((eq - eq.cummax()) / eq.cummax()).min()) if len(eq) else 0.0
        return {
            "trades": len(t), "net_pnl": round(sum(net), 2), "charges": round(sum(x["charges"] for x in t), 2),
            "win_rate": round(len(wins) / len(t), 3) if t else None,
            "expectancy": round(sum(net) / len(t), 2) if t else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown_pct": round(dd * 100, 2),
            "end_equity": round(float(eq.iloc[-1]), 2) if len(eq) else self.starting_cash,
        }

    def verdict(self) -> str:
        m = self.metrics()
        if m["trades"] < MIN_TRADES_FOR_EVIDENCE:
            return (f"INCONCLUSIVE: only {m['trades']} closed trades (< {MIN_TRADES_FOR_EVIDENCE}). "
                    "Not evidence of an edge either way.")
        if m["net_pnl"] <= 0:
            return "NO EDGE SHOWN: the autopilot lost money after charges over this replay."
        return "POSITIVE after modelled charges over this replay — still not proof; compare with the backtest's out-of-sample result."


def run_replay(settings: Settings, data_dir: str | Path, start: Optional[date], end: Optional[date],
               out_dir: str | Path, calendar: Optional[NSECalendar] = None) -> ReplayResult:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    s = settings.model_copy(update={"state_dir": str(out)})
    cal = calendar or NSECalendar()
    clock = [datetime.now(IST)]
    broker = PaperBroker(out / "paper.db", s.max_experimental_allocation_inr, s.charges,
                         slippage_bps=s.slippage_bps, clock=lambda: clock[0])
    journal = Journal(out / "journal.db", durable=False)
    pilot = AutoPilot(s, broker, journal, cal, data_dir)
    full = pilot.load_frames()
    if not full:
        raise ValueError(f"no valid CSVs for the watchlist {s.watchlist} in {data_dir}")
    for sym, df in full.items():
        _, rep_, _ = load_csv(Path(data_dir) / f"{sym}.csv", sym, cal)
        pilot.supervisor.preloaded[sym] = (df, rep_, pilot.sources[sym], add_indicators(df))
    days = sorted({d for df in full.values() for d in df["date"].dt.date})
    days = [d for d in days if (start is None or d >= start) and (end is None or d <= end)]
    if not days:
        raise ValueError("no trading days in the requested range")

    equity, signals, blocked, reasons = {}, 0, 0, {}
    last_close: dict[str, float] = {}
    for d in days:
        now = datetime.combine(d, time(15, 20), tzinfo=IST)
        clock[0] = now
        ts = pd.Timestamp(d)
        frames = {sym: df.iloc[: int(df["date"].searchsorted(ts, side="right"))] for sym, df in full.items()}
        quotes = {}
        for sym, df in frames.items():
            if len(df) and df["date"].iloc[-1] == ts:
                last_close[sym] = float(df["close"].iloc[-1])
                quotes[sym] = Quote(symbol=sym, price=last_close[sym], timestamp=now, source="replay:close (NOT live)")
        rep: TickReport = pilot.tick(now, quotes, as_of=d, frames=frames)
        signals += rep.signals
        for why in rep.blocked.values():
            blocked += 1
            for r in why:
                key = block_reason_key(r)
                reasons[key] = reasons.get(key, 0) + 1
        equity[pd.Timestamp(d)] = broker.cash() + sum(p.qty * last_close.get(p.symbol, p.avg_price)
                                                      for p in broker.get_positions())

    eq = pd.Series(equity)
    trades = broker.closed_trades()
    pd.DataFrame(trades).to_csv(out / "trades.csv", index=False)
    eq.rename("equity").to_csv(out / "equity.csv", index_label="date")
    sources = sorted(set(pilot.sources.values()))
    return ReplayResult(start=str(days[0]), end=str(days[-1]), days=len(days),
                        starting_cash=s.max_experimental_allocation_inr, equity=eq, trades=trades,
                        signals=signals, blocked=blocked, block_reasons=reasons, data_sources=sources, out_dir=str(out))


def format_replay(r: ReplayResult) -> str:
    m = r.metrics()
    lines = [
        f"REPLAY (paper autopilot, day by day) {r.start} → {r.end} | {r.days} trading days | start cash ₹{r.starting_cash:,.2f}",
        f"Data: {', '.join(r.data_sources) or 'see CSV source column'}",
        f"Signals {r.signals} | blocked by risk/charges {r.blocked} | closed trades {m['trades']}",
        f"Net P&L ₹{m['net_pnl']} (charges ₹{m['charges']}) | win rate {m['win_rate']} | expectancy ₹{m['expectancy']}/trade"
        f" | PF {m['profit_factor']} | max DD {m['max_drawdown_pct']}% | end equity ₹{m['end_equity']}",
    ]
    if r.block_reasons:
        top = sorted(r.block_reasons.items(), key=lambda kv: -kv[1])[:5]
        lines.append("Top block reasons: " + "; ".join(f"{k} ×{v}" for k, v in top))
    lines.append("VERDICT: " + r.verdict())
    lines.append(f"Files: {r.out_dir}/trades.csv, equity.csv, journal.db (separate from your real paper state)")
    return "\n".join(lines)
