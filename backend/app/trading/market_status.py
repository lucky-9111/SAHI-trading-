"""Market status engine: the backend's single answer to "is this exchange trading right now, and which session is it?".

Everything that decides whether an order may execute asks `is_open()` here, never the browser clock and never a price feed's flag.
Times are IST (Asia/Kolkata); the trading days, holidays, special sessions (Muhurat, Budget Sunday) and late opens come from the editable
market calendar in app.live.calendar.

States:
  OPEN        regular (or special) session: orders execute
  PRE_OPEN    NSE / BSE cash market 09:00-09:15 call auction. The paper engine does not simulate the auction: orders wait for the open
  POST_CLOSE  NSE / BSE cash market 15:40-16:00 closing-price session. Not simulated: orders wait for the next session
  CLOSED      a trading day, outside the session
  WEEKEND     Saturday / Sunday without a special session
  HOLIDAY     an exchange holiday on a weekday
`now()` is the engine's clock (UTC). Tests pin it with `set_clock()`; production never does.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.live import calendar

IST, UTC = calendar.IST, calendar.UTC

OPEN, PRE_OPEN, POST_CLOSE, CLOSED, WEEKEND, HOLIDAY = "OPEN", "PRE_OPEN", "POST_CLOSE", "CLOSED", "WEEKEND", "HOLIDAY"
LABELS = {OPEN: "Market open", PRE_OPEN: "Pre-open", POST_CLOSE: "Post-close", CLOSED: "Market closed", WEEKEND: "Market closed",
          HOLIDAY: "Market holiday"}
PRE_OPEN_MIN = 15                              # 09:00-09:15 before a 09:15 open
POST_CLOSE_WINDOW = (10, 30)                   # 15:40-16:00 after a 15:30 close
_AUCTION_EXCHANGES = {"NSE", "BSE"}            # cash market only; NFO / BFO / MCX go straight to the continuous session
EXCHANGES = ("NSE", "NFO", "BSE", "MCX")

_override: dt.datetime | None = None


def now() -> dt.datetime:
    return _override or dt.datetime.now(UTC)


def set_clock(t: dt.datetime | None) -> None:
    """Tests only: pin the engine clock (None = wall clock again)."""
    global _override
    _override = t.astimezone(UTC) if t is not None else None


def utc(t: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands datetimes back without a zone; everything this app stores is UTC."""
    if t is None:
        return None
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


@dataclass(frozen=True)
class MarketStatus:
    exchange: str
    state: str
    label: str
    is_open: bool                      # orders may execute now
    special: bool                      # today's session is a special one (Muhurat ...)
    note: str                          # holiday / special session name from the calendar
    session_start: dt.datetime | None  # today's session (UTC), when the exchange trades today
    session_end: dt.datetime | None
    next_open: dt.datetime | None      # when orders can next execute (None while open)
    server_time: dt.datetime

    def as_dict(self) -> dict:
        iso = lambda t: t.isoformat() if t else None  # noqa: E731
        return {"exchange": self.exchange, "state": self.state, "label": self.label, "is_open": self.is_open, "special": self.special,
                "note": self.note, "session_start": iso(self.session_start), "session_end": iso(self.session_end),
                "next_open": iso(self.next_open), "server_time": iso(self.server_time)}


def is_open(exchange: str = "NSE", at: dt.datetime | None = None) -> bool:
    return calendar.is_open(exchange, at or now())


def status(exchange: str = "NSE", at: dt.datetime | None = None) -> MarketStatus:
    n = (at or now()).astimezone(UTC)
    ex = exchange.upper()
    day = n.astimezone(IST).date()
    e = calendar.entry(ex, day)
    b = calendar.session_bounds(ex, day)
    special = bool(e and e["kind"] == "special" and b)
    note = (e or {}).get("note") or ""
    if b and b[0] <= n <= b[1]:
        state = OPEN
    elif b is None:
        state = WEEKEND if day.weekday() >= 5 else HOLIDAY
    elif n < b[0]:
        state = PRE_OPEN if ex in _AUCTION_EXCHANGES and not special and n >= b[0] - dt.timedelta(minutes=PRE_OPEN_MIN) else CLOSED
    elif ex in _AUCTION_EXCHANGES and not special and \
            b[1] + dt.timedelta(minutes=POST_CLOSE_WINDOW[0]) <= n < b[1] + dt.timedelta(minutes=POST_CLOSE_WINDOW[1]):
        state = POST_CLOSE
    else:
        state = CLOSED
    label = (f"Special session{f' · {note}' if note else ''}" if special and state == OPEN else LABELS[state])
    if state == HOLIDAY and note:
        label = f"Market holiday · {note}"
    return MarketStatus(ex, state, label, state == OPEN, special, note, b[0] if b else None, b[1] if b else None,
                        None if state == OPEN else calendar.next_open(ex, n), n)


def all_statuses(at: dt.datetime | None = None) -> list[MarketStatus]:
    n = at or now()
    return [status(ex, n) for ex in EXCHANGES]
