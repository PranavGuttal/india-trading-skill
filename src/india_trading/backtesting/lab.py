"""Strategy lab: every strategy vs the benchmarks, on one universe, in two
halves of the period (earlier = development, later = out-of-sample).

Verdict per strategy, judged on the LATER half (out-of-sample) and the full
period, after charges:
  BEATS BUY & HOLD      higher CAGR than equal-weight buy & hold in both
  SAFER, LOWER RETURN   smaller max drawdown than buy & hold but lower CAGR
  NO EDGE               loses money, or worse than buy & hold on both counts
Fewer than 30 trades in a half -> that half is INCONCLUSIVE.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from ..strategies import SIGNAL_STRATEGIES
from .portfolio import (LabConfig, LabResult, buy_and_hold, index_hold, run_regime_allocation, run_rotation,
                        run_signal_portfolio)

LAB_STRATEGIES = list(SIGNAL_STRATEGIES) + ["momentum_rotation", "trend_filtered_core", "etf_trend"]
MIN_TRADES = 30


@dataclass
class LabRow:
    name: str
    period: str
    metrics: dict


def _run(name: str, frames, nifty, etf, cfg) -> Optional[LabResult]:
    if name.endswith("+gate") and name[:-5] in SIGNAL_STRATEGIES:
        return run_signal_portfolio(frames, SIGNAL_STRATEGIES[name[:-5]], cfg, regime_index=nifty)
    if name in SIGNAL_STRATEGIES:
        return run_signal_portfolio(frames, SIGNAL_STRATEGIES[name], cfg)
    if name == "momentum_rotation":
        return run_rotation(frames, nifty, cfg)
    if name == "trend_filtered_core":
        return run_regime_allocation(frames, nifty, cfg)
    if name == "etf_trend":
        return run_regime_allocation(etf, nifty, cfg, name="etf_trend") if etf else None
    raise KeyError(f"unknown lab strategy {name!r}; choose from {', '.join(LAB_STRATEGIES)}")


def run_lab(frames: dict[str, pd.DataFrame], nifty: pd.DataFrame, etf: Optional[dict[str, pd.DataFrame]],
            strategies: list[str], cfg: LabConfig, split: date) -> tuple[list[LabRow], dict[str, str]]:
    periods = {"earlier": (cfg.start, split), "later (out-of-sample)": (split, cfg.end), "full": (cfg.start, cfg.end)}
    rows: list[LabRow] = []
    res: dict[tuple[str, str], dict] = {}
    for pname, (a, b) in periods.items():
        c = LabConfig(**{**cfg.__dict__, "start": a, "end": b})
        bench = [("NIFTY50 index (no costs)", index_hold(nifty, c)), ("buy & hold (equal weight)", buy_and_hold(frames, c))]
        if etf:
            bench.append(("NIFTYBEES buy & hold", buy_and_hold(etf, c)))
        for n, r in bench:
            rows.append(LabRow(n, pname, r.metrics()))
            res[(n, pname)] = r.metrics()
        for s in strategies:
            r = _run(s, frames, nifty, etf, c)
            if r is None:
                continue
            rows.append(LabRow(s, pname, r.metrics()))
            res[(s, pname)] = r.metrics()
    verdicts = {}
    for s in strategies:
        if (s, "full") not in res:
            continue
        parts = []
        bench = "NIFTYBEES buy & hold" if s == "etf_trend" else "buy & hold (equal weight)"   # like for like
        for p in ("later (out-of-sample)", "full"):
            m, bh = res[(s, p)], res[(bench, p)]
            if s.replace("+gate", "") in SIGNAL_STRATEGIES and m["trades"] < MIN_TRADES:
                parts.append("INCONCLUSIVE")
            elif m["cagr_pct"] > bh["cagr_pct"]:
                parts.append("BEATS")
            elif m["cagr_pct"] > 0 and m["max_drawdown_pct"] > bh["max_drawdown_pct"]:
                parts.append("SAFER")
            else:
                parts.append("NO")
        verdicts[s] = ("BEATS BUY & HOLD after charges (still not proof)" if parts == ["BEATS", "BEATS"] else
                       "SAFER, LOWER RETURN than buy & hold" if all(p in ("SAFER", "BEATS") for p in parts) else
                       "INCONCLUSIVE (too few trades)" if "INCONCLUSIVE" in parts else
                       "NO EDGE after charges")
    return rows, verdicts


COLS = [("cagr_pct", "CAGR%"), ("max_drawdown_pct", "maxDD%"), ("worst_year_pct", "worstYr%"),
        ("losing_months_pct", "lossMo%"), ("sharpe", "Sharpe"), ("trades", "trades"), ("win_rate_pct", "win%"),
        ("charges_inr", "charges₹"), ("exposure_pct", "invested%")]


def format_lab(rows: list[LabRow], verdicts: dict[str, str], header: str) -> str:
    lines = [header]
    for period in dict.fromkeys(r.period for r in rows):
        lines.append(f"\n  {period.upper()}")
        lines.append(f"  {'':28}" + "".join(f"{h:>10}" for _, h in COLS))
        for r in (x for x in rows if x.period == period):
            lines.append(f"  {r.name:28}" + "".join(f"{str(r.metrics.get(k)):>10}" for k, _ in COLS))
    lines.append("\n  VERDICTS (vs buy & hold of the same stocks; etf_trend vs holding NIFTYBEES; after Groww charges):")
    lines += [f"   {k:22} {v}" for k, v in verdicts.items()]
    lines.append("  Universe = today's large caps (survivorship bias flatters every long-only line). "
                 "Prices exclude dividends. Past results do not predict future results.")
    return "\n".join(lines)
