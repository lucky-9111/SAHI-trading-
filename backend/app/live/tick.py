"""The one tick shape every stage uses, and the normalizer that makes it from a raw SmartWebSocketV2 message."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

from app.live import calendar

IST = calendar.IST
UTC = calendar.UTC

EXCHANGE_BY_TYPE = {1: "NSE", 2: "NFO", 3: "BSE", 4: "BFO", 5: "MCX"}
TYPE_BY_EXCHANGE = {v: k for k, v in EXCHANGE_BY_TYPE.items()}
GRACE_AFTER_CLOSE_S = 30.0       # the last prints of a session carry a timestamp a few seconds after the close


@dataclass(frozen=True, slots=True)
class Tick:
    token: str
    symbol: str
    exchange: str
    ltp: float
    volume: int                   # cumulative volume traded today (0 when the feed mode carries none)
    exchange_ts: dt.datetime      # aware, IST: the exchange's own time of the trade
    received_ts: float            # time.time() when our process got it

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.token}"

    @property
    def utc(self) -> dt.datetime:
        return self.exchange_ts.astimezone(UTC)


class Normalizer:
    """raw dict -> Tick | None. Drops: ltp <= 0, a duplicate of the previous tick of that token, and ticks outside the exchange's session.

    `symbol_of(exchange, token)` names the token (None = unknown token, dropped). Counters tell why ticks were dropped."""

    def __init__(self, symbol_of: Callable[[str, str], str | None], check_session: bool = True):
        self.symbol_of = symbol_of
        self.check_session = check_session
        self._last: dict[str, tuple] = {}
        self.dropped = {"bad": 0, "price": 0, "duplicate": 0, "session": 0, "unknown": 0}

    def __call__(self, raw: dict, received_ts: float) -> Tick | None:
        try:
            ex = EXCHANGE_BY_TYPE.get(raw["exchange_type"])
            token = str(raw["token"]).strip('"')
            paise = raw["last_traded_price"]
            ms = raw["exchange_timestamp"]
        except (KeyError, TypeError):
            self.dropped["bad"] += 1
            return None
        if ex is None or not ms:
            self.dropped["bad"] += 1
            return None
        ltp = paise / 100.0                                   # Angel sends paise
        if ltp <= 0:
            self.dropped["price"] += 1
            return None
        symbol = self.symbol_of(ex, token)
        if symbol is None:
            self.dropped["unknown"] += 1
            return None
        ts = dt.datetime.fromtimestamp(ms / 1000.0, UTC).astimezone(IST)
        if self.check_session and not calendar.is_open(ex, ts, GRACE_AFTER_CLOSE_S):
            self.dropped["session"] += 1
            return None
        vol = int(raw.get("volume_trade_for_the_day") or 0)
        sig = (ltp, ms, vol)
        key = f"{ex}:{token}"
        if self._last.get(key) == sig:
            self.dropped["duplicate"] += 1
            return None
        self._last[key] = sig
        return Tick(token, symbol, ex, ltp, vol, ts, received_ts)
