"""NSE session awareness.

Regular equity session 09:15–15:30 IST, Monday–Friday. Exchange holidays
change every year and are NOT hard-coded: maintain config/nse_holidays.yaml
from the official NSE circular. If the file is missing or does not cover the
year, `holidays_verified` is False and the session status says so.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
CLOSE = time(15, 30)


@dataclass(frozen=True)
class SessionStatus:
    is_open: bool
    is_trading_day: bool
    reason: str
    holidays_verified: bool


class NSECalendar:
    def __init__(self, holidays: dict[int, set[date]] | None = None):
        self._holidays = holidays or {}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "NSECalendar":
        p = Path(path)
        if not p.exists():
            return cls({})
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        out: dict[int, set[date]] = {}
        for year, days in (raw.get("holidays") or {}).items():
            out[int(year)] = {date.fromisoformat(str(d)) for d in (days or [])}
        return cls(out)

    def covers(self, year: int) -> bool:
        return year in self._holidays

    def is_trading_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return d not in self._holidays.get(d.year, set())

    def status(self, now: datetime) -> SessionStatus:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        local = now.astimezone(IST)
        verified = self.covers(local.year)
        if local.weekday() >= 5:
            return SessionStatus(False, False, "weekend", verified)
        if local.date() in self._holidays.get(local.year, set()):
            return SessionStatus(False, False, "NSE holiday", verified)
        if local.time() < OPEN:
            return SessionStatus(False, True, "pre-open (before 09:15 IST)", verified)
        if local.time() >= CLOSE:
            return SessionStatus(False, True, "closed (after 15:30 IST)", verified)
        why = "regular session" if verified else "regular session (holiday list not verified for this year)"
        return SessionStatus(True, True, why, verified)
