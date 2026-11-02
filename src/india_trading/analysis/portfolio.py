"""Holdings review: what you own, how concentrated it is, and what needs a look.

Adapted from tradermonty portfolio-manager (Alpaca holdings analysis) and
kanchi-dividend-review-monitor (review TRIGGERS, never automatic selling),
for NSE holdings read from Groww (read-only connector) or a CSV export.

Input: rows of symbol, qty, avg_price (optional: stop). Prices come from the
latest close in the data folder unless current prices are given.
Review triggers (each is a reason to LOOK, not to sell):
  T1 below its 200-day average           T2 >= 20% below its 52-week high
  T3 position > 20% of the portfolio     T4 sector > 35% of the portfolio
  T5 latest 12-month dividends < the previous 12 months (dividend cut)
  T6 loss on the position worse than -15%
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Holding:
    symbol: str
    qty: float
    avg_price: float
    stop: Optional[float] = None


@dataclass
class HoldingView:
    symbol: str
    qty: float
    avg: float
    price: float
    value: float
    pnl: float
    pnl_pct: float
    weight: float
    sector: str
    vol: Optional[float]
    triggers: list[str] = field(default_factory=list)
    risk_to_stop: Optional[float] = None


@dataclass
class PortfolioReport:
    rows: list[HoldingView]
    total_value: float
    total_cost: float
    sector_weights: dict[str, float]
    avg_correlation: Optional[float]
    missing: list[str]
    notes: list[str] = field(default_factory=list)


_ALIASES = {"symbol": ["symbol", "tradingsymbol", "trading_symbol", "ticker", "scrip", "stock"],
            "qty": ["qty", "quantity", "shares", "holding_quantity", "net_qty"],
            "avg_price": ["avg_price", "average_price", "avg", "avg_cost", "buy_avg", "average"],
            "stop": ["stop", "stop_loss", "sl"]}


def _pick(d: dict, key: str):
    low = {str(k).strip().lower(): v for k, v in d.items()}
    for a in _ALIASES[key]:
        if a in low and low[a] not in (None, ""):
            return low[a]
    return None


def load_holdings(path: str | Path) -> list[Holding]:
    """CSV or JSON (a list of objects, or {"holdings": [...]}) with symbol,
    qty and average price columns under common names."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("holdings", data) if isinstance(data, dict) else data
    else:
        with open(p, newline="", encoding="utf-8-sig") as fh:
            items = list(csv.DictReader(fh))
    out = []
    for it in items:
        sym, qty, avg = _pick(it, "symbol"), _pick(it, "qty"), _pick(it, "avg_price")
        if sym is None or qty is None or avg is None:
            raise ValueError(f"holding row needs symbol, qty and average price: {it}")
        stop = _pick(it, "stop")
        out.append(Holding(str(sym).upper().replace("-EQ", "").strip(), float(qty), float(avg),
                           float(stop) if stop is not None else None))
    return out


def review(holdings: list[Holding], frames: dict[str, pd.DataFrame], sector_map: dict[str, dict],
           prices: Optional[dict[str, float]] = None, events: Optional[dict[str, list[dict]]] = None) -> PortfolioReport:
    prices = prices or {}
    rows, missing, rets = [], [], {}
    for h in holdings:
        df = frames.get(h.symbol)
        px = prices.get(h.symbol)
        if px is None and df is not None and len(df):
            px = float(df["close"].iloc[-1])
        if px is None:
            missing.append(h.symbol)
            continue
        v = HoldingView(h.symbol, h.qty, h.avg_price, round(px, 2), round(h.qty * px, 2),
                        round(h.qty * (px - h.avg_price), 2), round(100 * (px / h.avg_price - 1), 1), 0.0,
                        sector_map.get(h.symbol, {}).get("sector", "Unclassified"), None)
        if h.stop is not None:
            v.risk_to_stop = round(h.qty * max(0.0, px - h.stop), 2)
        if df is not None and len(df) >= 30:
            c = df["close"]
            r = c.pct_change().iloc[-252:]
            rets[h.symbol] = r.set_axis(pd.DatetimeIndex(df["date"].iloc[-len(r):]))
            v.vol = round(float(r.std() * np.sqrt(252) * 100), 1)
            if len(c) >= 200 and px < c.iloc[-200:].mean():
                v.triggers.append("T1 below 200-day average")
            hi = float(df["high"].iloc[-252:].max())
            if px <= 0.8 * hi:
                v.triggers.append(f"T2 {100 * (px / hi - 1):.0f}% from 52-week high")
        if v.pnl_pct <= -15:
            v.triggers.append(f"T6 position {v.pnl_pct:.0f}%")
        ev = (events or {}).get(h.symbol, [])
        if ev and df is not None and len(df):
            last = pd.Timestamp(df["date"].iloc[-1])
            d = [e for e in ev if e["type"] == "dividend"]
            y1 = sum(e["amount"] for e in d if pd.Timestamp(e["date"]) > last - pd.Timedelta(days=365))
            y0 = sum(e["amount"] for e in d if last - pd.Timedelta(days=730) < pd.Timestamp(e["date"]) <= last - pd.Timedelta(days=365))
            if y0 > 0 and y1 < 0.9 * y0:
                v.triggers.append(f"T5 dividends fell: ₹{y1:.2f} vs ₹{y0:.2f} a year earlier")
        rows.append(v)
    total = sum(r.value for r in rows)
    cost = sum(r.qty * r.avg for r in rows)
    sectors: dict[str, float] = {}
    for r in rows:
        r.weight = round(100 * r.value / total, 1) if total else 0.0
        sectors[r.sector] = round(sectors.get(r.sector, 0.0) + r.weight, 1)
        if r.weight > 20:
            r.triggers.append(f"T3 {r.weight:.0f}% of the portfolio")
    for r in rows:
        if sectors.get(r.sector, 0) > 35 and r.sector != "Unclassified":
            r.triggers.append(f"T4 sector {r.sector} is {sectors[r.sector]:.0f}%")
    corr = None
    if len(rets) >= 2:
        m = pd.DataFrame(rets).dropna().corr().to_numpy()
        iu = np.triu_indices_from(m, 1)
        corr = round(float(np.nanmean(m[iu])), 2)
    notes = []
    if corr is not None and corr > 0.6:
        notes.append(f"holdings move together (average correlation {corr}); diversification is lower than the count suggests")
    return PortfolioReport(sorted(rows, key=lambda r: -r.value), round(total, 2), round(cost, 2),
                           dict(sorted(sectors.items(), key=lambda kv: -kv[1])), corr, missing, notes)


def format_portfolio(r: PortfolioReport, source: str) -> str:
    pnl = r.total_value - r.total_cost
    lines = [f"PORTFOLIO REVIEW ({source}) — value ₹{r.total_value:,.2f}, cost ₹{r.total_cost:,.2f}, "
             f"P&L ₹{pnl:,.2f} ({100 * pnl / r.total_cost if r.total_cost else 0:+.1f}%)",
             f"  {'symbol':12}{'qty':>8}{'avg':>10}{'price':>10}{'value':>12}{'P&L%':>7}{'wt%':>6}{'vol%':>6}  sector / triggers"]
    for v in r.rows:
        lines.append(f"  {v.symbol:12}{v.qty:>8g}{v.avg:>10.2f}{v.price:>10.2f}{v.value:>12,.0f}{v.pnl_pct:>7.1f}"
                     f"{v.weight:>6.1f}{(v.vol if v.vol is not None else float('nan')):>6.1f}  {v.sector}"
                     + (f" | {'; '.join(v.triggers)}" if v.triggers else ""))
    lines.append("  Sectors: " + ", ".join(f"{k} {w:.0f}%" for k, w in r.sector_weights.items()))
    if r.avg_correlation is not None:
        lines.append(f"  Average pairwise correlation (1y daily): {r.avg_correlation}")
    if r.missing:
        lines.append(f"  No price for: {', '.join(r.missing)} (fetch their data or pass --prices)")
    lines += [f"  note: {n}" for n in r.notes]
    lines.append("  Triggers mean 'review this', never 'sell automatically'. Not advice.")
    return "\n".join(lines)
