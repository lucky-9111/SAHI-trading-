"""Live logs and incidents for the developer console.

A logging handler keeps the last few thousand lines in memory, with passwords, tokens, cookies and secrets masked before they are stored,
and groups WARNING / ERROR records of the app by cause (logger + message template). Both reset when the process restarts."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque

MASKS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"(?i)((?:access_|refresh_)?token[\"']?\s*[=:]\s*[\"']?)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"(?i)((?:password|passwd|pwd|secret|totp|api_key|apikey|pin|mpin|jwt|cookie)[\"']?\s*[=:]\s*[\"']?)[^\s,\"'&}]+"), r"\1***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "***jwt***"),
]
LINES = 3000
_lines: deque = deque(maxlen=LINES)                 # (ts, levelno, text)
_incidents: dict[tuple[str, str], dict] = {}
_recent: deque = deque(maxlen=200)
_lock = threading.Lock()


def mask(text: str) -> str:
    for rx, rep in MASKS:
        text = rx.sub(rep, text)
    return text


class ConsoleHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = mask(self.format(record))
        except Exception:  # noqa: BLE001
            return
        now = time.time()
        _lines.append((now, record.levelno, text))
        if record.levelno >= logging.WARNING and (record.name.startswith("app") or record.name.startswith("live")):
            first = mask(record.getMessage()).splitlines()[0][:300] if record.getMessage() else ""
            key = (record.name, str(record.msg)[:160])
            with _lock:
                inc = _incidents.get(key)
                if inc is None:
                    inc = _incidents[key] = {"component": record.name, "level": record.levelname, "message": first, "count": 0,
                                             "first_seen": now, "last_seen": now}
                inc["count"] += 1
                inc["last_seen"] = now
                inc["message"] = first
                _recent.append({"ts": now, "component": record.name, "level": record.levelname, "message": first})


_handler: ConsoleHandler | None = None


def install() -> None:
    global _handler
    if _handler is None:
        _handler = ConsoleHandler()
        logging.getLogger().addHandler(_handler)


def tail(n: int = 400, level: str = "") -> list[str]:
    lv = logging.getLevelName(level.upper()) if level else 0
    lv = lv if isinstance(lv, int) else 0
    rows = [t for _, lvl, t in list(_lines) if lvl >= lv]
    return rows[-max(1, min(n, LINES)):]


def incidents() -> dict:
    now = time.time()
    with _lock:
        grouped = sorted(_incidents.values(), key=lambda x: -x["last_seen"])
        recent = list(_recent)[-100:]
    hour = sum(1 for r in recent if now - r["ts"] <= 3600)
    return {"grouped": [{**g, "first_ago_s": round(now - g["first_seen"]), "last_ago_s": round(now - g["last_seen"])} for g in grouped],
            "recent": [{**r, "ago_s": round(now - r["ts"])} for r in reversed(recent)], "last_hour": hour}


def reset() -> None:
    _lines.clear()
    with _lock:
        _incidents.clear()
        _recent.clear()
