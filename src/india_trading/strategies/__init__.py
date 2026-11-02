"""Strategy registry. Signal strategies decide per stock; the rotation
strategy decides for a whole universe (portfolio lab / rotation autopilot)."""
from __future__ import annotations

from . import ma_trend, rotation
from .base import ExitPolicy, Strategy
from .trend import DONCHIAN, RSI2, TEMPLATE

SIGNAL_STRATEGIES: dict[str, Strategy] = {s.name: s for s in (ma_trend.STRATEGY, DONCHIAN, TEMPLATE, RSI2)}
ALL_NAMES = list(SIGNAL_STRATEGIES) + [rotation.NAME]
DEFAULT = ma_trend.NAME


def get(name: str | None) -> Strategy:
    key = (name or DEFAULT).strip()
    if key not in SIGNAL_STRATEGIES:
        raise KeyError(f"unknown signal strategy {key!r}; choose one of {', '.join(SIGNAL_STRATEGIES)}")
    return SIGNAL_STRATEGIES[key]
