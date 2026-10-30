"""Structured logging with secret redaction."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|api[_-]?key|totp|pin|otp|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+"),  # JWTs
]


def redact_text(s: str) -> str:
    for p in _PATTERNS:
        s = p.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=[REDACTED]", s)
    return s


class JsonRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        })


def setup_logging(level: str = "INFO", path: str | None = None) -> None:
    root = logging.getLogger("india_trading")
    root.setLevel(level)
    root.handlers.clear()
    h: logging.Handler = logging.FileHandler(path, encoding="utf-8") if path else logging.StreamHandler()
    h.setFormatter(JsonRedactingFormatter())
    root.addHandler(h)
