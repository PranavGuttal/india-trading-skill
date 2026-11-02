"""Event-driven daily backtester.

No look-ahead: the decision on bar t sees rows[0..t] only (indicators are
causal and are tested for it). Orders fill at the NEXT bar's open plus
slippage. Every trade must pass the same RiskManager used for paper trading,
including charges. Stops are checked before targets inside a bar
(conservative). Gaps through the stop fill at the open, not the stop.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators.core import add_indicators
from ..market_data.calendar import IST
from ..models import Quote, TradeProposal
from ..risk.costs import estimate_charges, roundtrip_costs
from ..risk.manager import AccountState, KillSwitch, RiskManager, block_reason_key, pnl_history_stats
from ..strategies.base import ExitPolicy, Strategy, close_rule_exit

MIN_TRADES_FOR_EVIDENCE = 30


@dataclass
class BTTrade:
    symbol: str
    entry_date: str
    exit_date: str
    qty: int
    entry: float
    exit: float
    charges: float
    pnl_gross: float
    pnl_net: float
    reason: str


@dataclass
class BTResult:
    symbol: str
    strategy: str
    trades: list[BTTrade]
    equity: pd.Series
    starting_capital: float
    days_in_market: int
    total_days: int
    signals: int
    blocked_by_risk: int
    block_reasons: dict[str, int] = field(default_factory=dict)
    baseline_net: float = 0.0
    split_index: int = 0
    data_source: str = ""

    def metrics(self, trades: list[BTTrade] | None = None) -> dict:
        t = self.trades if trades is None else trades
        wins = [x.pnl_net for x in t if x.pnl_net > 0]
        losses = [x.pnl_net for x in t if x.pnl_net <= 0]
        gross = sum(x.pnl_gross for x in t)
        net = sum(x.pnl_net for x in t)
        eq = self.equity
        dd = float(((eq - eq.cummax()) / eq.cummax()).min()) if len(eq) else 0.0
        turnover = sum(x.qty * (x.entry + x.exit) for x in t)
        return {
            "trades": len(t),
            "win_rate": round(len(wins) / len(t), 3) if t else None,
            "gross_pnl": round(gross, 2),
            "charges": round(sum(x.charges for x in t), 2),
            "net_pnl": round(net, 2),
            "avg_win": round(float(np.mean(wins)), 2) if wins else None,
            "avg_loss": round(float(np.mean(losses)), 2) if losses else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown_pct": round(dd * 100, 2),
            "exposure_pct": round(100 * self.days_in_market / max(1, self.total_days), 1),
            "turnover": round(turnover, 2),
        }

    def by_year(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for tr in self.trades:
            y = tr.exit_date[:4]
            d = out.setdefault(y, {"trades": 0, "net_pnl": 0.0})
            d["trades"] += 1
            d["net_pnl"] = round(float(d["net_pnl"]) + float(tr.pnl_net), 2)
        return out

    def verdict(self) -> str:
        n = len(self.trades)
        if n < MIN_TRADES_FOR_EVIDENCE:
            return f"INCONCLUSIVE: only {n} trades (< {MIN_TRADES_FOR_EVIDENCE}). Do not treat this as evidence of an edge."
        m = self.metrics()
        test = self.metrics([t for t in self.trades if t.entry_date >= self.split_date])
        if m["net_pnl"] <= 0 or test["net_pnl"] <= 0:
            return "NO EDGE SHOWN after charges (full period or out-of-sample test period is not positive)."
        return "POSITIVE in-sample and out-of-sample after modelled charges — still not proof; paper-trade before risking money."

    @property
    def split_date(self) -> str:
        return str(self.equity.index[self.split_index].date()) if len(self.equity) else ""


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    settings: Settings,
    strategy: Callable[..., TradeProposal] | Strategy,
    data_source: str = "",
    max_hold_days: int | None = None,
    train_fraction: float = 0.7,
    regime_index: pd.DataFrame | None = None,
) -> BTResult:
    """`strategy` is a Strategy (its exit policy applies) or a plain
    evaluate() callable (then: target, close < SMA50, max hold).
    With settings.regime_gate == "index", `regime_index` (Nifty 50 bars) feeds
    the market gate; without it the gate is switched off for this run."""
    if settings.regime_gate == "index" and regime_index is None:
        settings = settings.model_copy(update={"regime_gate": "off"})
    gate = None
    if regime_index is not None and settings.regime_gate == "index":
        g = regime_index.reset_index(drop=True)
        sm = g["close"].rolling(200, min_periods=200).mean()
        gate = pd.Series((g["close"] > sm).to_numpy(), index=pd.DatetimeIndex(g["date"]))
    if isinstance(strategy, Strategy):
        policy, name, evaluate = strategy.exit, strategy.name, strategy.evaluate
    else:
        policy = ExitPolicy(take_profit=True, close_below="sma50", max_hold_days=10)
        name = getattr(sys.modules.get(getattr(strategy, "__module__", ""), None), "NAME",
                       getattr(strategy, "__name__", "strategy"))
        evaluate = strategy
    if max_hold_days is not None:
        policy = ExitPolicy(**{**policy.__dict__, "max_hold_days": max_hold_days})
    df = df.reset_index(drop=True)
    x = add_indicators(df)
    rm = RiskManager(settings, KillSwitch(Path(settings.state_dir) / "__backtest_no_kill__"))
    slip = settings.slippage_bps / 10_000
    cash = settings.max_experimental_allocation_inr
    pos = None
    trades: list[BTTrade] = []
    equity_vals, dates = [], []
    signals = blocked = in_mkt = 0
    reasons: dict[str, int] = {}
    n = len(df)

    for t in range(n):
        row = df.iloc[t]
        d = pd.Timestamp(row["date"])
        # ---- manage open position on bar t
        if pos is not None and t >= pos["entry_idx"]:
            in_mkt += 1
            exit_px, why = None, ""
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]
            if t > pos["entry_idx"] and o <= pos["stop"]:
                exit_px, why = o, "gap below stop"
            elif l <= pos["stop"]:
                exit_px, why = pos["stop"], "stop" if pos["stop"] <= pos["entry"] else "trailing stop"
            elif policy.take_profit and h >= pos["target"]:
                exit_px, why = max(o, pos["target"]) if t > pos["entry_idx"] else pos["target"], "target"
            elif pos["exit_next_open"]:
                exit_px, why = o, pos["exit_next_open"]
            elif t - pos["entry_idx"] + 1 >= policy.max_hold_days:
                exit_px, why = c, "max hold"
            if exit_px is not None:
                px = exit_px * (1 - slip)
                ch = roundtrip_costs(pos["qty"] * pos["entry"], pos["qty"] * px, settings.product, settings.charges)
                gross = pos["qty"] * (px - pos["entry"])
                cash += pos["qty"] * px - (ch - pos["buy_costs"])
                trades.append(BTTrade(symbol, pos["entry_date"], str(d.date()), pos["qty"], round(pos["entry"], 2),
                                      round(px, 2), ch, round(gross, 2), round(gross - ch, 2), why))
                pos = None
            else:
                pos["hc"] = max(pos["hc"], c)
                atr_t = x["atr14"].iloc[t]
                if policy.trail_atr and not math.isnan(atr_t):
                    pos["stop"] = max(pos["stop"], round(pos["hc"] - policy.trail_atr * atr_t, 2))
                rule = close_rule_exit(policy, x.iloc[t])
                pos["exit_next_open"] = ("trend exit (close < SMA50)" if rule == "close < sma50" else rule) if rule else False

        # ---- mark to market
        mtm = cash + (pos["qty"] * row["close"] if pos else 0.0)
        equity_vals.append(mtm)
        dates.append(d)

        # ---- decide on close of t for t+1 (only if flat and a next bar exists)
        if pos is None and t + 1 < n:
            prop = evaluate(df.iloc[: t + 1], symbol, data_source, indicators=x.iloc[: t + 1])
            if prop.decision != "TRADE":
                continue
            signals += 1
            as_of = datetime.combine(d.date(), time(15, 30), tzinfo=IST)
            quote = Quote(symbol=symbol, price=float(row["close"]), timestamp=as_of, source="backtest-close")
            history = pnl_history_stats(((tr.exit_date, tr.pnl_net) for tr in trades), str(d.date()))
            acct = AccountState(cash_available=cash, open_positions=0, pending_orders=0,
                                realised_pnl_today=0.0, trades_today=0, verified=True, source="backtest", **history)
            market = None
            if gate is not None:
                k = int(gate.index.searchsorted(d, side="right"))
                ok = bool(gate.iloc[k - 1]) if k else None
                market = (ok, "market gate: Nifty 50 below its 200-day average — no new entries" if ok is False
                          else "market gate: no Nifty 50 data for this date")
            dec = rm.evaluate(prop, quote, acct, now=as_of, trade_date=str(d.date()), session_open=True, market=market)
            if not dec.approved:
                blocked += 1
                for r in dec.reasons:
                    key = block_reason_key(r)
                    reasons[key] = reasons.get(key, 0) + 1
                continue
            nxt = df.iloc[t + 1]
            fill = float(nxt["open"]) * (1 + slip)
            if fill <= prop.stop:
                blocked += 1
                reasons["next open gapped below stop; skipped"] = reasons.get("next open gapped below stop; skipped", 0) + 1
                continue
            qty = dec.qty
            buy_costs = estimate_charges(qty * fill, "BUY", settings.product, settings.charges).total
            while qty > 0 and qty * fill + buy_costs > cash:
                qty -= 1
                buy_costs = estimate_charges(qty * fill, "BUY", settings.product, settings.charges).total
            if qty <= 0:
                blocked += 1
                continue
            cash -= qty * fill + buy_costs
            pos = dict(qty=qty, entry=fill, stop=prop.stop, target=prop.target, entry_idx=t + 1, hc=fill,
                       entry_date=str(pd.Timestamp(nxt["date"]).date()), buy_costs=buy_costs, exit_next_open=False)

    equity = pd.Series(equity_vals, index=pd.DatetimeIndex(dates))
    # baseline: buy & hold with the same capital, one round trip of charges
    first_open, last_close = float(df["open"].iloc[0]), float(df["close"].iloc[-1])
    bq = int(settings.max_experimental_allocation_inr // first_open)
    baseline = bq * (last_close - first_open) - roundtrip_costs(bq * first_open, bq * last_close, "delivery", settings.charges) if bq else 0.0
    return BTResult(
        symbol=symbol, strategy=name, trades=trades, equity=equity,
        starting_capital=settings.max_experimental_allocation_inr, days_in_market=in_mkt, total_days=n,
        signals=signals, blocked_by_risk=blocked, block_reasons=reasons, baseline_net=round(baseline, 2),
        split_index=min(n - 1, int(n * train_fraction)), data_source=data_source,
    )


def format_report(res: BTResult) -> str:
    m = res.metrics()
    train = res.metrics([t for t in res.trades if t.entry_date < res.split_date])
    test = res.metrics([t for t in res.trades if t.entry_date >= res.split_date])
    lines = [
        f"BACKTEST {res.symbol} | strategy {res.strategy} | data {res.data_source}",
        f"Period {res.equity.index[0].date()} → {res.equity.index[-1].date()} ({res.total_days} bars)  capital ₹{res.starting_capital:,.2f}",
        f"Signals {res.signals} | blocked by risk/charges {res.blocked_by_risk} | trades {m['trades']}",
        f"Net P&L ₹{m['net_pnl']} (gross ₹{m['gross_pnl']}, charges ₹{m['charges']}) | win rate {m['win_rate']} | PF {m['profit_factor']}",
        f"Avg win {m['avg_win']} | avg loss {m['avg_loss']} | max DD {m['max_drawdown_pct']}% | exposure {m['exposure_pct']}% | turnover ₹{m['turnover']}",
        f"Train (< {res.split_date}): trades {train['trades']} net ₹{train['net_pnl']} | Test (>= {res.split_date}): trades {test['trades']} net ₹{test['net_pnl']}",
        f"Baseline buy & hold (same capital, after charges): ₹{res.baseline_net}",
        f"By year: {res.by_year()}",
    ]
    if res.block_reasons:
        top = sorted(res.block_reasons.items(), key=lambda kv: -kv[1])[:5]
        lines.append("Top block reasons: " + "; ".join(f"{k} ×{v}" for k, v in top))
    lines.append("VERDICT: " + res.verdict())
    return "\n".join(lines)
