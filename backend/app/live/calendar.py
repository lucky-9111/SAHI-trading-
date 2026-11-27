"""Market calendar: which exchange is open at which moment.

Base sessions (IST): NSE / NFO 09:15-15:30, BSE 09:15-15:30, MCX 09:00-23:30 (23:55 while US daylight saving time is in force).
Exceptions live in the `market_calendar` table and are read with a one-minute cache, so they can be edited without a deploy:
  holiday   -> closed all day, also on a weekday
  special   -> a session with its own start / end (Muhurat, Budget Sunday), also on a weekend
  late_open -> a normal day that starts late (MCX on an NSE holiday: from 17:00); the normal close applies
Every question goes through `session()` / `is_open()`; nothing else in the app hard-codes trading hours.
"""
from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

_BASE = {"NSE": (dt.time(9, 15), dt.time(15, 30)), "BSE": (dt.time(9, 15), dt.time(15, 30)), "MCX": (dt.time(9, 0), dt.time(23, 30))}
_ALIAS = {"NFO": "NSE", "BFO": "BSE", "CDS": "NSE"}
_CACHE_S = 60.0
_cache: dict[tuple[str, str], dict] | None = None
_cache_at = 0.0


def canon(exchange: str) -> str:
    return _ALIAS.get(exchange, exchange)


def _load() -> dict[tuple[str, str], dict]:
    global _cache, _cache_at
    if _cache is not None and time.time() - _cache_at < _CACHE_S:
        return _cache
    data: dict[tuple[str, str], dict] = {}
    try:
        from sqlalchemy import select

        from app.database.session import SessionLocal
        from app.models.live import MarketCalendarRow

        with SessionLocal() as db:
            for r in db.scalars(select(MarketCalendarRow)):
                data[(r.date, r.exchange)] = {"kind": r.kind, "start": r.start_time, "end": r.end_time, "note": r.note}
    except Exception:  # noqa: BLE001  (a missing table or a busy database means "no exceptions")
        if _cache is not None:
            return _cache
    _cache, _cache_at = data, time.time()
    return data


def invalidate() -> None:
    global _cache
    _cache = None


def override(entries: dict[tuple[str, str], dict] | None) -> None:
    """Tests: replace the exception list (None goes back to the database)."""
    global _cache, _cache_at
    _cache, _cache_at = entries, time.time() + 10**9 if entries is not None else 0.0


def _t(s: str) -> dt.time:
    return dt.time.fromisoformat(s)


def mcx_close(day: dt.date) -> dt.time:
    """MCX trades until 23:55 while the US is on daylight saving time, otherwise until 23:30."""
    noon_ny = dt.datetime.combine(day, dt.time(12, 0), tzinfo=NY)
    return dt.time(23, 55) if noon_ny.dst() else dt.time(23, 30)


def session(exchange: str, day: dt.date) -> tuple[dt.time, dt.time] | None:
    """(open, close) in IST on that day, or None when the exchange is closed all day."""
    ex = canon(exchange)
    e = _load().get((day.isoformat(), ex))
    if e and e["kind"] == "special" and e["start"] and e["end"]:
        return _t(e["start"]), _t(e["end"])
    if day.weekday() >= 5 or (e and e["kind"] == "holiday"):
        return None
    start, end = _BASE.get(ex, _BASE["NSE"])
    if ex == "MCX":
        end = mcx_close(day)
    if e and e["kind"] == "late_open" and e["start"]:
        start = _t(e["start"])
    return start, end


def _ist(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now(UTC)).astimezone(IST)


def is_open(exchange: str, now: dt.datetime | None = None, grace_after_close_s: float = 0.0) -> bool:
    n = _ist(now)
    s = session(exchange, n.date())
    if not s:
        return False
    start = dt.datetime.combine(n.date(), s[0], tzinfo=IST)
    end = dt.datetime.combine(n.date(), s[1], tzinfo=IST) + dt.timedelta(seconds=grace_after_close_s)
    return start <= n <= end


def session_bounds(exchange: str, day: dt.date) -> tuple[dt.datetime, dt.datetime] | None:
    """Session start / end of that day as aware UTC datetimes."""
    s = session(exchange, day)
    if not s:
        return None
    return (dt.datetime.combine(day, s[0], tzinfo=IST).astimezone(UTC), dt.datetime.combine(day, s[1], tzinfo=IST).astimezone(UTC))


def next_close(exchange: str, now: dt.datetime | None = None) -> dt.datetime:
    """The next session end after `now` (UTC): today's if it has not passed, else the next trading day's."""
    n = _ist(now)
    for i in range(0, 15):
        day = n.date() + dt.timedelta(days=i)
        b = session_bounds(exchange, day)
        if b and b[1] > n.astimezone(UTC):
            return b[1]
    raise RuntimeError("no trading day in the next 15 days")


def put(db, day: str, exchange: str, kind: str, start: str | None = None, end: str | None = None, note: str = "") -> None:
    """Add or change an entry (used by scripts/calendar_admin.py and the NSE holiday sync)."""
    from sqlalchemy import select

    from app.models.live import MarketCalendarRow

    dt.date.fromisoformat(day)
    if kind not in ("holiday", "special", "late_open") or canon(exchange) not in _BASE:
        raise ValueError("kind: holiday|special|late_open; exchange: NSE|BSE|MCX")
    if kind == "special" and not (start and end and _t(start) < _t(end)):
        raise ValueError("a special session needs start < end")
    if kind == "late_open" and not start:
        raise ValueError("a late open needs the opening time")
    row = db.scalar(select(MarketCalendarRow).where(MarketCalendarRow.date == day, MarketCalendarRow.exchange == canon(exchange)))
    if row is None:
        row = MarketCalendarRow(date=day, exchange=canon(exchange))
        db.add(row)
    row.kind, row.start_time, row.end_time, row.note = kind, start, end if kind == "special" else None, note[:200]
    db.commit()
    invalidate()
