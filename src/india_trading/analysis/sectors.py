"""NSE sector rotation from real sector-index data (Nifty Bank, IT, Auto, ...).

Adapted from tradermonty's sector-analyst and theme-detector. Each sector
index is scored by its return over 1, 3 and 6 months RELATIVE to Nifty 50
(0.2 / 0.4 / 0.4 weights) and its trend (close vs 50/200-day averages).
Leaders = strongest relative strength in an uptrend; laggards = weakest.
Also maps universe stocks to their sector (config/sectors.yaml, editable,
approximate) so a scan can prefer stocks in leading sectors.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml


@dataclass
class SectorRow:
    name: str
    close: float
    r1m: float
    r3m: float
    r6m: float
    rs1m: float
    rs3m: float
    rs6m: float
    score: float
    above50: bool
    above200: bool
    trend: str


def _ret(c: pd.Series, n: int) -> float:
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else float("nan")


def rank(sectors: dict[str, pd.DataFrame], nifty: pd.DataFrame, as_of: Optional[date] = None) -> list[SectorRow]:
    def cut(df):
        df = df.reset_index(drop=True)
        return df[df["date"].dt.date <= as_of] if as_of else df
    n = cut(nifty)["close"]
    nr = {k: _ret(n, k) for k in (21, 63, 126)}
    rows = []
    for name, df in sectors.items():
        c = cut(df)["close"].reset_index(drop=True)
        if len(c) < 201:
            continue
        r = {k: _ret(c, k) for k in (21, 63, 126)}
        rs = {k: r[k] - nr[k] for k in r}
        a50, a200 = c.iloc[-1] > c.iloc[-50:].mean(), c.iloc[-1] > c.iloc[-200:].mean()
        trend = "uptrend" if a50 and a200 else "downtrend" if not a50 and not a200 else "mixed"
        rows.append(SectorRow(name, round(float(c.iloc[-1]), 2), *(round(100 * r[k], 1) for k in (21, 63, 126)),
                              *(round(100 * rs[k], 1) for k in (21, 63, 126)),
                              round(100 * (0.2 * rs[21] + 0.4 * rs[63] + 0.4 * rs[126]), 2), bool(a50), bool(a200), trend))
    return sorted(rows, key=lambda r: -r.score)


def load_sector_map(path: str | Path = "config/sectors.yaml") -> dict[str, dict]:
    """symbol -> {sector, index}. Missing file -> {}."""
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for sector, spec in (data.get("sectors") or {}).items():
        for sym in spec.get("symbols", []):
            out[str(sym).upper()] = {"sector": sector, "index": spec.get("index")}
    return out


def format_sectors(rows: list[SectorRow], as_of: str) -> str:
    lines = [f"NSE SECTOR ROTATION as of {as_of} — return vs Nifty 50 (percentage points); Yahoo Finance, unofficial",
             f"  {'sector':18}{'1m':>7}{'3m':>7}{'6m':>7}{'RS1m':>7}{'RS3m':>7}{'RS6m':>7}{'score':>8}  trend"]
    for r in rows:
        lines.append(f"  {r.name:18}{r.r1m:>7}{r.r3m:>7}{r.r6m:>7}{r.rs1m:>7}{r.rs3m:>7}{r.rs6m:>7}{r.score:>8}  {r.trend}")
    lead = [r.name for r in rows if r.trend == "uptrend"][:3]
    lag = [r.name for r in reversed(rows) if r.trend == "downtrend"][:3]
    lines.append(f"  Leaders (strong RS and in an uptrend): {', '.join(lead) or 'none'}")
    lines.append(f"  Laggards (weak RS and in a downtrend): {', '.join(lag) or 'none'}")
    lines.append("  Relative strength describes the past; it is not a forecast.")
    return "\n".join(lines)
