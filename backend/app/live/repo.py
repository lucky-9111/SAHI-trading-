"""Closed candles in the database, and the backfill of minutes the feed missed."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable

from sqlalchemy import select

from app.database.session import SessionLocal
from app.live import calendar
from app.live.candles import Candle, floor_minute
from app.models.live import LiveCandle

log = logging.getLogger(__name__)
UTC, IST = calendar.UTC, calendar.IST


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)      # SQLite returns naive datetimes: they were stored as UTC


def upsert_candles(candles: list[Candle], session_factory=SessionLocal) -> int:
    """Insert closed candles; a (token, tf, time) that exists is updated by a 'live' candle and left alone by a 'hist' one."""
    if not candles:
        return 0
    n = 0
    with session_factory() as db:
        for c in candles:
            row = db.scalar(select(LiveCandle).where(LiveCandle.token == c.token, LiveCandle.tf == c.tf, LiveCandle.ts == c.start))
            if row is None:
                db.add(LiveCandle(exchange=c.exchange, token=c.token, symbol=c.symbol, tf=c.tf, ts=c.start, open=c.open, high=c.high,
                                  low=c.low, close=c.close, volume=c.volume, source=c.source))
                n += 1
            elif c.source == "live":
                row.open, row.high, row.low, row.close, row.volume, row.source = c.open, c.high, c.low, c.close, c.volume, "live"
        db.commit()
    return n


def load_recent(exchange: str, token: str, tf: str, limit: int = 500, session_factory=SessionLocal) -> list[Candle]:
    with session_factory() as db:
        rows = db.scalars(select(LiveCandle).where(LiveCandle.token == token, LiveCandle.tf == tf, LiveCandle.exchange == exchange)
                          .order_by(LiveCandle.ts.desc()).limit(limit)).all()
    return [Candle(r.token, r.symbol, r.exchange, r.tf, _aware(r.ts), r.open, r.high, r.low, r.close, r.volume, r.source)
            for r in reversed(rows)]


def minute_starts(exchange: str, token: str, since: dt.datetime, session_factory=SessionLocal) -> set[dt.datetime]:
    with session_factory() as db:
        rows = db.scalars(select(LiveCandle.ts).where(LiveCandle.token == token, LiveCandle.exchange == exchange, LiveCandle.tf == "1m",
                                                      LiveCandle.ts >= since)).all()
    return {_aware(r) for r in rows}


# fetcher(exchange, token, start_ist_naive, end_ist_naive) -> [[iso_ts, o, h, l, c, v], ...]
Fetcher = Callable[[str, str, dt.datetime, dt.datetime], list[list]]


def broker_fetcher(exchange: str, token: str, start: dt.datetime, end: dt.datetime) -> list[list]:
    from app.market_data import angel
    from app.market_data.provider import NoData

    try:
        return angel.provider.get_candles(exchange, token, "ONE_MINUTE", start, end)
    except NoData:
        return []


def backfill_minutes(exchange: str, token: str, symbol: str, known: set[dt.datetime], now: dt.datetime,
                     fetch: Fetcher = broker_fetcher) -> list[Candle]:
    """1-minute candles of today's session that we do NOT have, from the historical API.

    The window is [session open (or the first missing minute), the current minute): the minute in progress is left to the live ticks, so a minute
    is never built twice. Minutes in `known` (live candles already closed, or stored earlier) are skipped: nothing is double-counted."""
    now = now.astimezone(UTC)
    b = calendar.session_bounds(exchange, now.astimezone(IST).date())
    if b is None:
        return []
    start, end = b[0], min(floor_minute(now), b[1])
    if end <= start:
        return []
    have = {k for k in known if start <= k < end}
    # skip the part of the session that is already complete: start from the first minute we do not have
    t = start
    while t in have and t < end:
        t += dt.timedelta(minutes=1)
    if t >= end:
        return []
    rows = fetch(exchange, token, t.astimezone(IST).replace(tzinfo=None), end.astimezone(IST).replace(tzinfo=None))
    out: list[Candle] = []
    for r in rows:
        ts = dt.datetime.fromisoformat(str(r[0])[:19]).replace(tzinfo=IST).astimezone(UTC)
        if ts in have or not (start <= ts < end):
            continue
        out.append(Candle(token, symbol, exchange, "1m", ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5] or 0), "hist"))
        have.add(ts)
    out.sort(key=lambda c: c.start)
    return out
