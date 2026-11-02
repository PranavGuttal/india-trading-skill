"""Supervisor: a plain state machine for one symbol.

LOAD -> VALIDATE -> ANALYZE -> RISK -> TICKET -> (APPROVAL) -> EXECUTE -> JOURNAL -> DONE
Any failed step moves to HALTED with a reason; nothing after it runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from ..brokers.base import BrokerAdapter
from ..config import Settings
from ..execution.executor import Approval, ExecutionAgent, ExecutionRefused
from ..execution.manual_ticket import render_ticket
from ..journal.store import Journal
from ..market_data.calendar import IST, NSECalendar
from ..market_data.csv_source import DataError, is_stale, load_csv
from ..models import Quote, RiskDecision, TradeProposal
from ..risk.manager import RiskManager
from ..analysis.market_gate import market_ok
from ..paths import config_file
from ..strategies import get as get_strategy


class Step(str, Enum):
    LOAD = "LOAD"
    VALIDATE = "VALIDATE"
    ANALYZE = "ANALYZE"
    RISK = "RISK"
    TICKET = "TICKET"
    APPROVAL = "APPROVAL"
    EXECUTE = "EXECUTE"
    DONE = "DONE"
    HALTED = "HALTED"


@dataclass
class RunState:
    symbol: str
    step: Step = Step.LOAD
    halted_reason: str = ""
    proposal: Optional[TradeProposal] = None
    decision: Optional[RiskDecision] = None
    ticket: str = ""
    log: list[str] = field(default_factory=list)
    execution_status: str = ""

    def halt(self, why: str) -> "RunState":
        self.step, self.halted_reason = Step.HALTED, why
        self.log.append(f"HALTED: {why}")
        return self


class Supervisor:
    def __init__(self, settings: Settings, broker: BrokerAdapter, journal: Journal,
                 calendar: Optional[NSECalendar] = None, strategy: Optional[Callable] = None):
        self.s = settings
        self.broker = broker
        self.journal = journal
        self.calendar = calendar or NSECalendar.from_yaml(config_file("nse_holidays.yaml"))
        self.strategy = strategy or get_strategy(settings.strategy).evaluate
        self.risk = RiskManager(settings)
        self.exec = ExecutionAgent(settings, broker, journal)
        # symbol -> (df, validation report, source, indicators) loaded once by a replay.
        # Indicators are causal, so slicing them by row count equals recomputing.
        self.preloaded: dict[str, tuple] = {}

    @property
    def mode(self) -> str:
        return "live" if self.broker.is_live else "paper"

    def analyze(self, symbol: str, csv_path: Path, today: date, as_of: Optional[date] = None) -> RunState:
        st = RunState(symbol)
        ind = None
        if symbol in self.preloaded:
            df, rep, source, ind = self.preloaded[symbol]
        else:
            try:
                df, rep, source = load_csv(csv_path, symbol, self.calendar)
            except DataError as e:
                return st.halt(f"data: {e}")
        if as_of is not None:
            n = int(df["date"].searchsorted(pd.Timestamp(as_of), side="right"))
            df = df.iloc[:n]
            ind = ind.iloc[:n] if ind is not None else None
            if df.empty:
                return st.halt(f"no bars on or before {as_of}")
            source += f" [replay as of {as_of}]"
        st.step = Step.VALIDATE
        if not rep.ok:
            return st.halt("data invalid: " + "; ".join(rep.errors))
        st.log += [f"data warning: {w}" for w in rep.warnings]
        stale = is_stale(df, today, self.s.max_bar_age_days)
        st.step = Step.ANALYZE
        prop = self.strategy(df, symbol, source) if ind is None else self.strategy(df, symbol, source, indicators=ind)
        if stale and prop.decision == "TRADE":
            prop = TradeProposal(decision="NO_TRADE", symbol=symbol, strategy=prop.strategy,
                                 strategy_version=prop.strategy_version, as_of=prop.as_of, data_source=source,
                                 reasons=[f"latest bar {prop.as_of.date()} is older than {self.s.max_bar_age_days} business days"],
                                 contra=prop.reasons)
        st.proposal = prop
        self.journal.record("SIGNAL" if prop.decision == "TRADE" else "NO_TRADE", self.mode,
                            "; ".join(prop.reasons)[:500], symbol=symbol, strategy=prop.strategy,
                            strategy_version=prop.strategy_version, data_source=source,
                            data_as_of=prop.as_of.isoformat(), payload=prop.model_dump(mode="json"))
        st.log.append(f"{prop.decision}: " + "; ".join(prop.reasons))
        return st

    def run_once(self, symbol: str, csv_path: Path, quote: Optional[Quote], now: datetime,
                 approve: Optional[Callable[[str, str], Optional[str]]] = None,
                 as_of: Optional[date] = None) -> RunState:
        """approve(ticket, intent_id) -> the user's reply text, or None to decline."""
        today = now.astimezone(IST).date()
        st = self.analyze(symbol, csv_path, today, as_of=as_of)
        if st.step == Step.HALTED or st.proposal is None:
            return st
        if st.proposal.decision != "TRADE":
            st.step = Step.DONE
            return st
        st.step = Step.RISK
        try:
            account = self.broker.get_account_state(str(today))
        except Exception as e:  # unverifiable account -> fail closed
            account = None
            st.log.append(f"account state unavailable: {e}")
        session = self.calendar.status(now)
        market = market_ok(self.s.indices_dir, as_of or today, self.s.max_bar_age_days) \
            if self.s.regime_gate == "index" else None
        dec = self.risk.evaluate(st.proposal, quote, account, now=now, trade_date=str(today),
                                 session_open=session.is_open, market=market)
        st.decision = dec
        self.journal.record("RISK_APPROVED" if dec.approved else "RISK_BLOCKED", self.mode,
                            "; ".join(dec.reasons) or "all checks passed", symbol=symbol,
                            data_source=st.proposal.data_source,
                            intent_id=dec.intent.intent_id if dec.intent else None,
                            payload={**dec.model_dump(mode="json"), "quote_source": quote.source if quote else None})
        st.step = Step.TICKET
        st.ticket = render_ticket(st.proposal, dec, self.mode)
        if not dec.approved:
            return st.halt("risk manager blocked: " + "; ".join(dec.reasons))
        self.journal.record("TICKET", self.mode, st.ticket[:500], symbol=symbol, intent_id=dec.intent.intent_id)

        st.step = Step.APPROVAL
        reply = None
        if self.s.require_human_approval:
            self.journal.record("APPROVAL_REQUESTED", self.mode, "waiting for explicit yes", symbol=symbol,
                                intent_id=dec.intent.intent_id)
            reply = approve(st.ticket, dec.intent.intent_id) if approve else None
            if not reply:
                self.journal.record("DECLINED", self.mode, "no approval given", symbol=symbol, intent_id=dec.intent.intent_id)
                return st.halt("not approved by user")
            self.journal.record("APPROVED", self.mode, f"reply: {reply[:60]}", symbol=symbol, intent_id=dec.intent.intent_id)
        st.step = Step.EXECUTE
        try:
            res = self.exec.execute(dec, Approval(dec.intent.intent_id, reply) if reply else None)
        except ExecutionRefused as e:
            self.journal.record("ERROR", self.mode, f"execution refused: {e}", symbol=symbol)
            return st.halt(f"execution refused: {e}")
        st.execution_status = res.status
        st.log.append(f"execution: {res.status} {res.message}")
        st.step = Step.DONE
        return st
