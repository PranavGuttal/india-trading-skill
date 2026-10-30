"""Controlled polling monitor. Read-only: it NEVER places orders.

Runs as a foreground process; stops on Ctrl+C, on `monitor stop` (stop file),
or when the kill switch is engaged. Writes a heartbeat JSON for health checks.
It cannot monitor anything while this process or the computer is not running.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from ..config import Settings
from ..journal.store import Journal
from ..market_data.calendar import IST, NSECalendar
from ..market_data.csv_source import DataError, is_stale, load_csv
from ..risk.manager import KillSwitch
from ..strategies import ma_trend

log = logging.getLogger("india_trading.monitor")


class Monitor:
    def __init__(self, settings: Settings, journal: Journal, calendar: NSECalendar, data_dir: Path,
                 clock: Callable[[], datetime] = lambda: datetime.now(IST)):
        self.s, self.journal, self.calendar, self.data_dir, self.clock = settings, journal, calendar, Path(data_dir), clock
        self.stop_file = settings.state_path("MONITOR_STOP")
        self.heartbeat = settings.state_path("monitor_heartbeat.json")
        self.kill = KillSwitch(settings.state_path("KILL_SWITCH"))

    def request_stop(self) -> None:
        self.stop_file.write_text("stop\n", encoding="utf-8")

    def tick(self) -> dict:
        now = self.clock()
        session = self.calendar.status(now)
        results = {}
        for sym in self.s.watchlist:
            path = self.data_dir / f"{sym}.csv"
            try:
                df, rep, src = load_csv(path, sym, self.calendar)
            except DataError as e:
                results[sym] = f"NO DATA ({e})"
                continue
            if not rep.ok:
                results[sym] = "INVALID DATA: " + "; ".join(rep.errors)
                continue
            if is_stale(df, now.date(), self.s.max_bar_age_days):
                results[sym] = f"STALE (last bar {df['date'].iloc[-1].date()})"
                continue
            p = ma_trend.evaluate(df, sym, src)
            results[sym] = f"{p.decision}: " + "; ".join(p.reasons)[:160]
        beat = {"ts": now.isoformat(), "session": session.reason, "market_open": session.is_open,
                "kill_switch": self.kill.engaged, "results": results,
                "note": "read-only monitor; no orders are placed"}
        self.heartbeat.write_text(json.dumps(beat, indent=2), encoding="utf-8")
        return beat

    def run(self, interval_s: int = 300, max_ticks: Optional[int] = None) -> int:
        if interval_s < 30:
            raise ValueError("polling interval must be >= 30s to respect data-source limits")
        if self.stop_file.exists():
            self.stop_file.unlink()
        ticks = 0
        try:
            while True:
                if self.kill.engaged:
                    log.warning("kill switch engaged; monitor stopping")
                    break
                if self.stop_file.exists():
                    log.info("stop requested")
                    self.stop_file.unlink()
                    break
                try:
                    beat = self.tick()
                    log.info("tick %s session=%s", beat["ts"], beat["session"])
                except Exception as e:  # keep running, record it
                    self.journal.record("ERROR", "paper", f"monitor tick failed: {e}")
                    log.exception("tick failed")
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                time.sleep(interval_s)
        except KeyboardInterrupt:
            log.info("interrupted; shutting down cleanly")
        return ticks
