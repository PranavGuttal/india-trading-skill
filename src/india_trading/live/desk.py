"""Live desk: turns a strategy signal into a PREPARED live ticket, or refuses.

Order of locks (all must pass, each fails closed):
  1. every live switch (trading_mode=live, live_trading_enabled, LIVE_TRADING_ACK phrase)
  2. kill switch off (checked again inside the risk manager)
  3. graduation passed on the forward paper account (entries only; exits only reduce risk)
  4. full analysis + RiskManager with a cash figure read from Groww
The desk never sends an order. Claude sends exactly the approved ticket via
the Groww connector, and the guard hook checks it against this ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..brokers.groww_adapter import GrowwAdapter
from ..brokers.paper_broker import PaperBroker
from ..config import Settings
from ..execution.manual_ticket import render_ticket
from ..journal.store import Journal
from ..market_data.calendar import IST, NSECalendar
from ..models import OrderIntent, Quote, Side
from ..risk.manager import KillSwitch, RiskManager
from ..workflows.supervisor import Step, Supervisor
from .graduation import Graduation, check as check_graduation
from .ledger import LiveLedger


@dataclass
class DeskResult:
    ok: bool
    message: str
    ticket: Optional[dict] = None
    text: str = ""
    reasons: list[str] = field(default_factory=list)


def graduation_for(settings: Settings, journal: Journal) -> Graduation:
    paper = PaperBroker(settings.state_path("paper.db"), settings.max_experimental_allocation_inr, settings.charges)
    with paper._conn() as c:
        buys = [r[0] for r in c.execute("SELECT intent_id FROM orders WHERE side='BUY' AND filled_qty > 0")]
    return check_graduation(settings, paper.closed_trades(), buys, journal.events(mode="paper", limit=1_000_000))


def _locks(settings: Settings) -> list[str]:
    why = []
    if not settings.live_requested:
        why.append("live switches are off (needs trading_mode=live, live_trading_enabled=true and the "
                   "LIVE_TRADING_ACK phrase)")
    if KillSwitch(settings.state_path("KILL_SWITCH")).engaged:
        why.append("kill switch is engaged")
    return why


class LiveDesk:
    def __init__(self, settings: Settings, journal: Journal, calendar: NSECalendar, data_dir: str | Path):
        self.s, self.journal, self.calendar, self.data_dir = settings, journal, calendar, Path(data_dir)
        self.ledger = LiveLedger(settings.state_path("live.db"))

    def prepare_entry(self, symbol: str, price: float, price_source: str, broker_cash: Optional[float],
                      now: Optional[datetime] = None) -> DeskResult:
        now = now or datetime.now(IST)
        sym = symbol.upper()
        locks = _locks(self.s)
        g = graduation_for(self.s, self.journal)
        if not g.passed:
            locks.append("graduation not passed: " + "; ".join(g.reasons))
        if locks:
            self.journal.record("RISK_BLOCKED", "live", "live locked: " + "; ".join(locks)[:400], symbol=sym)
            return DeskResult(False, "LIVE LOCKED", reasons=locks)

        # GrowwAdapter refuses every call; it only makes the journal record this analysis as mode=live.
        sup = Supervisor(self.s, GrowwAdapter(), self.journal, self.calendar)
        st = sup.analyze(sym, self.data_dir / f"{sym}.csv", now.date())
        if st.step == Step.HALTED or st.proposal is None:
            return DeskResult(False, "HALTED", reasons=[st.halted_reason])
        if st.proposal.decision != "TRADE":
            return DeskResult(False, "NO_TRADE", reasons=st.proposal.reasons)
        quote = Quote(symbol=sym, price=price, timestamp=now, source=f"manual:{price_source}")
        account = self.ledger.account_state(self.s, str(now.date()), broker_cash)
        dec = RiskManager(self.s).evaluate(st.proposal, quote, account, now=now, trade_date=str(now.date()),
                                           session_open=self.calendar.status(now).is_open)
        self.journal.record("RISK_APPROVED" if dec.approved else "RISK_BLOCKED", "live",
                            "; ".join(dec.reasons) or "all checks passed", symbol=sym,
                            data_source=st.proposal.data_source,
                            intent_id=dec.intent.intent_id if dec.intent else None,
                            payload={**dec.model_dump(mode="json"), "quote_source": quote.source})
        text = render_ticket(st.proposal, dec, mode="live")
        if not dec.approved or dec.intent is None:
            return DeskResult(False, "RISK BLOCKED", text=text, reasons=dec.reasons)
        t = self.ledger.prepare(dec.intent, "ENTRY", now)
        self.journal.record("TICKET", "live", text[:500], symbol=sym, intent_id=t["intent_id"])
        return DeskResult(True, "PREPARED", ticket=t, text=text)

    def prepare_exit(self, symbol: str, price: float, price_source: str, reason: str,
                     now: Optional[datetime] = None) -> DeskResult:
        """Exits need the live switches but not graduation or entry limits: they only reduce risk."""
        now = now or datetime.now(IST)
        sym = symbol.upper()
        if not self.s.live_requested:
            return DeskResult(False, "LIVE LOCKED", reasons=["live switches are off; sell it yourself in the Groww app"])
        pos = self.ledger.positions().get(sym)
        if pos is None:
            return DeskResult(False, "NO POSITION", reasons=[f"the live ledger holds no {sym}"])
        intent = OrderIntent(symbol=sym, side=Side.SELL, qty=pos["qty"], limit_price=round(price * 0.995, 2),
                             product=self.s.product, trade_date=str(now.date()),
                             proposal_ref=f"live-exit:{reason}:{now.isoformat()}")
        t = self.ledger.prepare(intent, "EXIT", now)
        text = (f"=== LIVE EXIT TICKET [REAL MONEY via Groww] ===\nSELL {intent.qty} x {sym} (NSE)  LIMIT ₹{intent.limit_price:.2f}"
                f"  product={intent.product}\nReason: {reason}; price ₹{price} from {price_source} at {now:%H:%M:%S} IST\n"
                f"intent_id {t['intent_id']}")
        self.journal.record("TICKET", "live", text[:500], symbol=sym, intent_id=t["intent_id"])
        return DeskResult(True, "PREPARED", ticket=t, text=text)
