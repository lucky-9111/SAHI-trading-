"""In-memory measurements for the developer console (reset on restart): HTTP requests, Angel One calls, background heartbeats.
Nothing here makes an extra call; it only records the calls the app already makes."""
from __future__ import annotations

import statistics
import threading
import time
from collections import deque

STARTED = time.time()
_lock = threading.Lock()
_http: deque = deque(maxlen=20000)                 # (ts, status, ms)
_angel: dict[str, deque] = {}                      # endpoint -> (ts, ms, outcome, error)
_angel_last_error: dict[str, tuple[float, str]] = {}
_beats: dict[str, float] = {}

ANGEL_LABELS = {"candles": ("Candles (history)", "getCandleData"), "quote": ("Quotes (batch)", "getMarketData"),
                "ltp": ("Last price", "ltpData"), "login": ("Login", "generateSession")}


def http(status: int, ms: float) -> None:
    _http.append((time.time(), status, ms))


def angel(endpoint: str, ms: float, outcome: str, error: str = "") -> None:
    """outcome: ok | error | rate_limited"""
    with _lock:
        _angel.setdefault(endpoint, deque(maxlen=5000)).append((time.time(), ms, outcome))
        if outcome != "ok":
            _angel_last_error[endpoint] = (time.time(), error[:200])


def beat(name: str) -> None:
    _beats[name] = time.time()


def beat_age(name: str) -> float | None:
    t = _beats.get(name)
    return None if t is None else time.time() - t


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 2)


def http_summary(window: float = 300) -> dict:
    cut = time.time() - window
    rows = [r for r in list(_http) if r[0] >= cut]
    errors = sum(1 for r in rows if r[1] >= 500)
    return {"requests": len(rows), "server_errors": errors, "error_pct": round(100 * errors / len(rows), 2) if rows else 0.0,
            "p95_ms": _pct([r[2] for r in rows], 0.95), "window_s": window}


def angel_summary(window: float = 3600) -> dict:
    cut = time.time() - window
    out, calls, errors, limited = [], 0, 0, 0
    with _lock:
        items = {k: [r for r in v if r[0] >= cut] for k, v in _angel.items()}
        last_err = dict(_angel_last_error)
    for ep, rows in sorted(items.items()):
        ms = [r[1] for r in rows]
        e = sum(1 for r in rows if r[2] == "error")
        rl = sum(1 for r in rows if r[2] == "rate_limited")
        calls, errors, limited = calls + len(rows), errors + e, limited + rl
        le = last_err.get(ep)
        label, api = ANGEL_LABELS.get(ep, (ep, ep))
        out.append({"endpoint": ep, "label": label, "api": api, "count": len(rows),
                    "median_ms": round(statistics.median(ms), 1) if ms else None, "p95_ms": _pct(ms, 0.95),
                    "slowest_ms": round(max(ms), 1) if ms else None, "errors": e, "rate_limited": rl,
                    "last_ago_s": round(time.time() - rows[-1][0]) if rows else None,
                    "last_error": le[1] if le else None, "last_error_ago_s": round(time.time() - le[0]) if le else None})
    return {"window_s": window, "calls": calls, "errors": errors, "rate_limited": limited, "endpoints": out}


def uptime_s() -> float:
    return time.time() - STARTED


def reset() -> None:
    """Tests only."""
    _http.clear()
    _angel.clear()
    _angel_last_error.clear()
    _beats.clear()
