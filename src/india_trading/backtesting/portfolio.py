"""Portfolio-level strategy lab: many stocks, one cash account.

Same honesty rules as the single-stock backtester:
- decisions on the close of day t use rows <= t; orders fill at the NEXT
  open plus slippage; a gap through the stop fills at the open;
- inside a bar the stop is checked before the target;
- every buy and sell pays Groww charges from risk/costs.py (incl. DP charge);
- benchmarks over the same window: Nifty 50 (price index, no costs) and an
  equal-weight buy & hold of the same universe (charges paid once).

Signal strategies size each trade by risk (risk_pct of equity between entry
and stop), capped at max_position_pct of equity and by cash. The rotation
strategy holds top_n stocks in equal weight and rebalances monthly.
Survivorship bias: the universe is today's large caps, which flatters every
long-only result (strategies AND buy & hold) — compare against the
benchmarks, never against zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from ..config import ChargeSchedule
from ..indicators.core import add_indicators
from ..risk.costs import estimate_charges, roundtrip_costs
from ..strategies import rotation
from ..strategies.base import Strategy


@dataclass
class LabConfig:
    capital: float = 100_000.0
    max_positions: int = 5
    risk_pct: float = 0.01
    max_position_pct: float = 0.20
    slippage_bps: float = 10.0
    start: Optional[date] = None
    end: Optional[date] = None
    product: str = "delivery"
    charges: ChargeSchedule = field(default_factory=ChargeSchedule)


@dataclass
class LabTrade:
    symbol: str
    entry_date: str
    exit_date: str
    qty: int
    entry: float
    exit: float
    charges: float
    pnl_net: float
    reason: str
    days: int


@dataclass
class LabResult:
    name: str
    equity: pd.Series
    trades: list[LabTrade]
    invested: pd.Series
    capital: float
    note: str = ""

    def metrics(self) -> dict:
        eq = self.equity
        if eq.empty:
            return {}
        years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
        total = eq.iloc[-1] / eq.iloc[0] - 1
        rets = eq.pct_change().dropna()
        dd = float((eq / eq.cummax() - 1).min())
        cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1.0
        t = self.trades
        wins = [x for x in t if x.pnl_net > 0]
        return {
            "final_inr": round(float(eq.iloc[-1]), 0),
            "total_return_pct": round(100 * total, 1),
            "cagr_pct": round(100 * cagr, 1),
            "max_drawdown_pct": round(100 * dd, 1),
            "sharpe": round(float(rets.mean() / rets.std() * math.sqrt(252)), 2) if rets.std() > 0 else None,
            "mar": round(cagr / abs(dd), 2) if dd < 0 else None,
            "trades": len(t),
            "win_rate_pct": round(100 * len(wins) / len(t), 1) if t else None,
            "avg_hold_days": round(float(np.mean([x.days for x in t])), 1) if t else None,
            "charges_inr": round(sum(x.charges for x in t), 0),
            "exposure_pct": round(100 * float(self.invested.mean()), 1) if len(self.invested) else 0.0,
            **self.loss_stats(),
        }

    def loss_stats(self) -> dict:
        """How often and how badly it lost: worst calendar year and month, share of losing months."""
        eq = self.equity
        if len(eq) < 2:
            return {"worst_year_pct": None, "worst_month_pct": None, "losing_months_pct": None}
        m = eq.resample("ME").last()
        mr = m.pct_change().dropna()
        first = m.iloc[0] / eq.iloc[0] - 1
        mr = pd.concat([pd.Series([first], index=[m.index[0]]), mr])
        return {"worst_year_pct": min(self.yearly().values()) if self.yearly() else None,
                "worst_month_pct": round(100 * float(mr.min()), 1),
                "losing_months_pct": round(100 * float((mr < 0).mean()), 1)}

    def yearly(self) -> dict[str, float]:
        eq = self.equity
        out = {}
        for y, s in eq.groupby(eq.index.year):
            prev = eq[eq.index.year < y]
            base = prev.iloc[-1] if len(prev) else s.iloc[0]
            out[str(y)] = round(100 * (s.iloc[-1] / base - 1), 1)
        return out


# ---------------------------------------------------------------- helpers
def _window(cal: pd.DatetimeIndex, cfg: LabConfig) -> pd.DatetimeIndex:
    w = cal
    if cfg.start:
        w = w[w >= pd.Timestamp(cfg.start)]
    if cfg.end:
        w = w[w <= pd.Timestamp(cfg.end)]
    if len(w) < 2:
        raise ValueError("window has fewer than 2 trading days")
    return w


def _master_calendar(frames: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex([])
    for df in frames.values():
        idx = idx.union(pd.DatetimeIndex(df["date"]))
    return idx.sort_values()


def _sell_costs(qty: int, entry: float, px: float, buy_costs: float, cfg: LabConfig) -> float:
    return roundtrip_costs(qty * entry, qty * px, cfg.product, cfg.charges) - buy_costs


def _buy_costs(value: float, cfg: LabConfig) -> float:
    return estimate_charges(value, "BUY", cfg.product, cfg.charges).total


def _arrays(x: pd.DataFrame, cal: pd.DatetimeIndex, cols: list[str]) -> dict[str, np.ndarray]:
    y = x.set_index(pd.DatetimeIndex(x["date"])).reindex(cal)
    return {c: y[c].to_numpy(dtype=float) for c in cols}


# ---------------------------------------------------------------- signal strategies
def run_signal_portfolio(frames: dict[str, pd.DataFrame], strat: Strategy, cfg: LabConfig,
                         regime_index: Optional[pd.DataFrame] = None, regime_sma: int = 200) -> LabResult:
    """regime_index: when given, NO NEW ENTRIES on days the index closes at or
    below its `regime_sma`-day average (open positions keep their exits)."""
    cal_all = _master_calendar(frames)
    cal = _window(cal_all, cfg)
    slip = cfg.slippage_bps / 10_000
    pol = strat.exit
    data = {}
    for sym, df in frames.items():
        x = add_indicators(df.reset_index(drop=True))
        sg = strat.signals(x)
        x = x.assign(sig=sg["signal"].astype(float), stop=sg["stop"], target=sg["target"], score=sg["score"])
        c = x["close"]
        rule = pd.Series(False, index=x.index)
        if pol.close_below:
            rule |= c < x[pol.close_below]
        if pol.close_above:
            rule |= c > x[pol.close_above]
        x["rule"] = rule.astype(float)
        data[sym] = _arrays(x, cal, ["open", "high", "low", "close", "atr14", "sig", "stop", "target", "score", "rule"])

    gate = None
    if regime_index is not None:
        ok = rotation.regime_ok(regime_index.reset_index(drop=True), rotation.RotationParams(regime_sma=regime_sma))
        gate = pd.Series(ok.to_numpy(), index=pd.DatetimeIndex(regime_index["date"])).reindex(cal, method="ffill")             .fillna(False).to_numpy()
    cash = cfg.capital
    pos: dict[str, dict] = {}
    pending: list[tuple[str, float, float]] = []      # (symbol, stop, target) to buy at today's open
    trades: list[LabTrade] = []
    eq_vals, inv_vals = [], []
    last_close = {s: np.nan for s in data}

    def close_pos(sym, i, px, why):
        nonlocal cash
        p = pos.pop(sym)
        px = px * (1 - slip)
        sc = _sell_costs(p["qty"], p["entry"], px, p["buy_costs"], cfg)
        cash += p["qty"] * px - sc
        tot = p["buy_costs"] + sc
        trades.append(LabTrade(sym, str(cal[p["i"]].date()), str(cal[i].date()), p["qty"], round(p["entry"], 2),
                               round(px, 2), round(tot, 2), round(p["qty"] * (px - p["entry"]) - tot, 2), why,
                               int(i - p["i"])))

    for i in range(len(cal)):
        # 1. pending entries fill at today's open
        equity_open = cash + sum(p["qty"] * (last_close[s] if not np.isnan(last_close[s]) else p["entry"])
                                 for s, p in pos.items())
        for sym, stop, target in pending:
            d = data[sym]
            o = d["open"][i]
            if np.isnan(o) or sym in pos or len(pos) >= cfg.max_positions:
                continue
            fill = o * (1 + slip)
            if fill <= stop:
                continue
            qty = int(min(cfg.risk_pct * equity_open / (fill - stop), cfg.max_position_pct * equity_open / fill))
            while qty > 0 and qty * fill + _buy_costs(qty * fill, cfg) > cash:
                qty -= 1
            if qty <= 0:
                continue
            bc = _buy_costs(qty * fill, cfg)
            cash -= qty * fill + bc
            pos[sym] = dict(qty=qty, entry=fill, stop=stop, target=target, i=i, hc=fill, buy_costs=bc, exit_next=False)
        pending = []

        # 2. manage open positions on today's bar
        for sym in list(pos):
            d, p = data[sym], pos[sym]
            o, h, l, c = d["open"][i], d["high"][i], d["low"][i], d["close"][i]
            if np.isnan(o):
                continue
            if p["exit_next"]:
                close_pos(sym, i, o, p["exit_next"])
                continue
            first = i == p["i"]
            if not first and o <= p["stop"]:
                close_pos(sym, i, o, "gap below stop")
            elif l <= p["stop"]:
                close_pos(sym, i, p["stop"], "stop" if p["stop"] <= p["entry"] else "trailing stop")
            elif pol.take_profit and h >= p["target"]:
                close_pos(sym, i, p["target"] if first else max(o, p["target"]), "target")
            elif i - p["i"] + 1 >= pol.max_hold_days:
                close_pos(sym, i, c, "max hold")
            else:
                p["hc"] = max(p["hc"], c)
                if pol.trail_atr and not np.isnan(d["atr14"][i]):
                    p["stop"] = max(p["stop"], round(p["hc"] - pol.trail_atr * d["atr14"][i], 2))
                if d["rule"][i] == 1.0:
                    p["exit_next"] = "close rule (" + (pol.close_below and f"close < {pol.close_below}" or
                                                       f"close > {pol.close_above}") + ")"

        # 3. mark to market
        for sym, d in data.items():
            if not np.isnan(d["close"][i]):
                last_close[sym] = d["close"][i]
        mv = sum(p["qty"] * last_close[s] for s, p in pos.items())
        eq_vals.append(cash + mv)
        inv_vals.append(mv / (cash + mv) if cash + mv > 0 else 0.0)

        # 4. new signals on today's close -> tomorrow's open
        if i + 1 < len(cal) and (gate is None or gate[i]):
            slots = cfg.max_positions - len(pos)
            if slots > 0:
                cands = [(d["score"][i], sym) for sym, d in data.items()
                         if sym not in pos and d["sig"][i] == 1.0 and not np.isnan(d["open"][i + 1])]
                cands.sort(key=lambda t: -(t[0] if not np.isnan(t[0]) else -1e9))
                pending = [(sym, data[sym]["stop"][i], data[sym]["target"][i]) for _, sym in cands[:slots]]

    for sym in list(pos):                      # mark open positions out at the last close (charges included)
        close_pos(sym, len(cal) - 1, last_close[sym], "end of test (marked)")
    eq = pd.Series(eq_vals, index=cal)
    eq.iloc[-1] = cash
    return LabResult(strat.name + ("+gate" if gate is not None else ""), eq, trades, pd.Series(inv_vals, index=cal),
                     cfg.capital, note="no new entries while Nifty 50 <= SMA200" if gate is not None else "")


# ---------------------------------------------------------------- rotation
def run_rotation(frames: dict[str, pd.DataFrame], index_df: Optional[pd.DataFrame], cfg: LabConfig,
                 p: rotation.RotationParams = rotation.PARAMS) -> LabResult:
    cal = _window(_master_calendar(frames), cfg)
    slip = cfg.slippage_bps / 10_000
    data = {}
    for sym, df in frames.items():
        x = add_indicators(df.reset_index(drop=True))
        x["mscore"] = rotation.momentum_score(x)
        data[sym] = _arrays(x, cal, ["open", "close", "mscore"])
    reg = None
    if index_df is not None:
        ix = index_df.set_index(pd.DatetimeIndex(index_df["date"]))
        ok = rotation.regime_ok(index_df.reset_index(drop=True), p)
        reg = pd.Series(ok.to_numpy(), index=ix.index).reindex(cal, method="ffill").fillna(False).to_numpy()

    cash = cfg.capital
    pos: dict[str, dict] = {}
    trades: list[LabTrade] = []
    eq_vals, inv_vals = [], []
    last_close = {s: np.nan for s in data}
    orders: Optional[tuple[set, list]] = None        # (sells, buys) for today's open
    month_end = np.r_[cal.month[1:] != cal.month[:-1], False]

    for i in range(len(cal)):
        if orders is not None:
            sells, buys = orders
            for sym in sells:
                o = data[sym]["open"][i]
                px = (o if not np.isnan(o) else last_close[sym]) * (1 - slip)
                q = pos.pop(sym)
                sc = _sell_costs(q["qty"], q["entry"], px, q["buy_costs"], cfg)
                cash += q["qty"] * px - sc
                tot = q["buy_costs"] + sc
                trades.append(LabTrade(sym, str(cal[q["i"]].date()), str(cal[i].date()), q["qty"], round(q["entry"], 2),
                                       round(px, 2), round(tot, 2), round(q["qty"] * (px - q["entry"]) - tot, 2),
                                       q.get("why", "rebalance"), int(i - q["i"])))
            equity = cash + sum(q["qty"] * last_close[s] for s, q in pos.items())
            per = equity / p.top_n
            for sym in buys:
                o = data[sym]["open"][i]
                if np.isnan(o) or sym in pos:
                    continue
                fill = o * (1 + slip)
                qty = int(min(per, cash) / fill)
                while qty > 0 and qty * fill + _buy_costs(qty * fill, cfg) > cash:
                    qty -= 1
                if qty <= 0:
                    continue
                bc = _buy_costs(qty * fill, cfg)
                cash -= qty * fill + bc
                pos[sym] = dict(qty=qty, entry=fill, i=i, buy_costs=bc)
            orders = None

        for sym, d in data.items():
            if not np.isnan(d["close"][i]):
                last_close[sym] = d["close"][i]
        mv = sum(q["qty"] * last_close[s] for s, q in pos.items())
        eq_vals.append(cash + mv)
        inv_vals.append(mv / (cash + mv) if cash + mv > 0 else 0.0)

        if month_end[i]:
            regime = True if reg is None else bool(reg[i])
            ranked = rotation.rank_universe({s: d["mscore"][i] for s, d in data.items()})
            rank = {s: k + 1 for k, (s, _) in enumerate(ranked)}
            if not regime:
                sells = set(pos)
                for s in sells:
                    pos[s]["why"] = "regime off (Nifty < SMA200)"
                buys = []
            else:
                keep = {s for s in pos if rank.get(s, 10**6) <= p.hold_rank}
                sells = set(pos) - keep
                for s in sells:
                    pos[s]["why"] = "rank dropped" if s in rank else "lost eligibility (below SMA200)"
                buys = [s for s, _ in ranked if s not in keep][: max(0, p.top_n - len(keep))]
            if sells or buys:
                orders = (sells, buys)

    for sym in list(pos):
        q = pos.pop(sym)
        px = last_close[sym] * (1 - slip)
        sc = _sell_costs(q["qty"], q["entry"], px, q["buy_costs"], cfg)
        cash += q["qty"] * px - sc
        trades.append(LabTrade(sym, str(cal[q["i"]].date()), str(cal[-1].date()), q["qty"], round(q["entry"], 2),
                               round(px, 2), round(q["buy_costs"] + sc, 2),
                               round(q["qty"] * (px - q["entry"]) - q["buy_costs"] - sc, 2), "end of test (marked)",
                               int(len(cal) - 1 - q["i"])))
    eq = pd.Series(eq_vals, index=cal)
    eq.iloc[-1] = cash
    return LabResult(rotation.NAME, eq, trades, pd.Series(inv_vals, index=cal), cfg.capital,
                     note="regime: Nifty 50 > SMA200" if reg is not None else "no regime index loaded")


# ---------------------------------------------------------------- benchmarks
def buy_and_hold(frames: dict[str, pd.DataFrame], cfg: LabConfig) -> LabResult:
    """Equal weight in every stock at the first open, held to the end (charges once)."""
    cal = _window(_master_calendar(frames), cfg)
    per = cfg.capital / max(1, len(frames))
    cash, held, trades = cfg.capital, {}, []
    closes = {}
    for sym, df in frames.items():
        a = _arrays(df, cal, ["open", "close"])
        first = next((k for k in range(len(cal)) if not np.isnan(a["open"][k])), None)
        if first is None:
            continue
        fill = a["open"][first] * (1 + cfg.slippage_bps / 10_000)
        qty = int(per / fill)
        if qty <= 0:
            continue
        bc = _buy_costs(qty * fill, cfg)
        cash -= qty * fill + bc
        held[sym] = (qty, fill, bc, first)
        # before a late listing's first bar the money is committed at its fill price
        closes[sym] = pd.Series(a["close"], index=cal).ffill().fillna(fill)
    mv = sum(q * closes[s] for s, (q, _, _, _) in held.items())
    eq = cash + mv.fillna(0) if len(held) else pd.Series(cfg.capital, index=cal)
    for s, (q, f, bc, k) in held.items():
        px = float(closes[s].iloc[-1])
        sc = _sell_costs(q, f, px, bc, cfg)
        cash += q * px - sc
        trades.append(LabTrade(s, str(cal[k].date()), str(cal[-1].date()), q, round(f, 2), round(px, 2),
                               round(bc + sc, 2), round(q * (px - f) - bc - sc, 2), "buy & hold", len(cal) - 1 - k))
    eq = eq.astype(float)
    eq.iloc[-1] = cash
    inv = (mv / eq).fillna(0) if len(held) else pd.Series(0.0, index=cal)
    return LabResult("equal_weight_buy_hold", eq, trades, inv, cfg.capital)


def index_hold(index_df: pd.DataFrame, cfg: LabConfig, name: str = "NIFTY50") -> LabResult:
    """The index itself (price index, no costs, no dividends): what an index fund roughly tracks."""
    s = index_df.set_index(pd.DatetimeIndex(index_df["date"]))["close"]
    cal = _window(pd.DatetimeIndex(s.index), cfg)
    s = s.reindex(cal).ffill()
    eq = cfg.capital * s / s.iloc[0]
    return LabResult(f"{name}_index", eq, [], pd.Series(1.0, index=cal), cfg.capital,
                     note="price index; no costs or dividends")


# ---------------------------------------------------------------- trend-filtered core
def run_regime_allocation(frames: dict[str, pd.DataFrame], index_df: pd.DataFrame, cfg: LabConfig,
                          sma_days: int = 200, name: str = "trend_filtered_core") -> LabResult:
    """Equal weight in every instrument while the index closes above its
    `sma_days` average on the last trading day of a month; cash otherwise.
    Trades only when the regime flips (no periodic rebalancing), so charges
    stay small. Idea: Faber (2007) 10-month / 200-day timing rule;
    tradermonty exposure-coach and market-top-detector."""
    cal = _window(_master_calendar(frames), cfg)
    slip = cfg.slippage_bps / 10_000
    data = {s: _arrays(df, cal, ["open", "close"]) for s, df in frames.items()}
    ok = rotation.regime_ok(index_df.reset_index(drop=True), rotation.RotationParams(regime_sma=sma_days))
    reg = pd.Series(ok.to_numpy(), index=pd.DatetimeIndex(index_df["date"])).reindex(cal, method="ffill") \
        .fillna(False).to_numpy()
    month_end = np.r_[cal.month[1:] != cal.month[:-1], False]
    cash, pos, trades = cfg.capital, {}, []
    eq_vals, inv_vals = [], []
    last_close = {s: np.nan for s in data}
    action = None
    for i in range(len(cal)):
        if action == "sell":
            for sym in list(pos):
                q = pos.pop(sym)
                o = data[sym]["open"][i]
                px = (o if not np.isnan(o) else last_close[sym]) * (1 - slip)
                sc = _sell_costs(q["qty"], q["entry"], px, q["buy_costs"], cfg)
                cash += q["qty"] * px - sc
                trades.append(LabTrade(sym, str(cal[q["i"]].date()), str(cal[i].date()), q["qty"], round(q["entry"], 2),
                                       round(px, 2), round(q["buy_costs"] + sc, 2),
                                       round(q["qty"] * (px - q["entry"]) - q["buy_costs"] - sc, 2),
                                       "regime off (index < SMA)", int(i - q["i"])))
        elif action == "buy":
            live = [s for s in data if not np.isnan(data[s]["open"][i])]
            per = cash / max(1, len(live))
            for sym in live:
                fill = data[sym]["open"][i] * (1 + slip)
                qty = int(per / fill)
                while qty > 0 and qty * fill + _buy_costs(qty * fill, cfg) > cash:
                    qty -= 1
                if qty <= 0:
                    continue
                bc = _buy_costs(qty * fill, cfg)
                cash -= qty * fill + bc
                pos[sym] = dict(qty=qty, entry=fill, i=i, buy_costs=bc)
        action = None
        for sym, d in data.items():
            if not np.isnan(d["close"][i]):
                last_close[sym] = d["close"][i]
        mv = sum(q["qty"] * last_close[s] for s, q in pos.items())
        eq_vals.append(cash + mv)
        inv_vals.append(mv / (cash + mv) if cash + mv > 0 else 0.0)
        if month_end[i] or i == 0:
            if reg[i] and not pos:
                action = "buy"
            elif not reg[i] and pos:
                action = "sell"
    for sym in list(pos):
        q = pos.pop(sym)
        px = last_close[sym] * (1 - slip)
        sc = _sell_costs(q["qty"], q["entry"], px, q["buy_costs"], cfg)
        cash += q["qty"] * px - sc
        trades.append(LabTrade(sym, str(cal[q["i"]].date()), str(cal[-1].date()), q["qty"], round(q["entry"], 2),
                               round(px, 2), round(q["buy_costs"] + sc, 2),
                               round(q["qty"] * (px - q["entry"]) - q["buy_costs"] - sc, 2), "end of test (marked)",
                               int(len(cal) - 1 - q["i"])))
    eq = pd.Series(eq_vals, index=cal)
    eq.iloc[-1] = cash
    return LabResult(name, eq, trades, pd.Series(inv_vals, index=cal), cfg.capital,
                     note=f"index > SMA{sma_days} at month end; cash earns nothing here")
