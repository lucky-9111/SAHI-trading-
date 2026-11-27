"""Candle building. Pure logic with an injectable clock, so replays and tests are deterministic.

  ticks --CandleBuilder--> closed 1-minute candles --Aggregator--> closed 5m / 15m / 1d candles

* A 1m candle for minute M closes when the first tick of a LATER minute arrives, or when `flush(now)` is called after M+1:00 + 2 s
  (so a quiet symbol still closes).
* Higher timeframes are built from the closed 1-minute candles only, never from ticks. Buckets start at the exchange's session open
  (NSE 09:15, MCX 09:00 ...), the last bucket of a session is shorter and closes at the session end.
* Minutes are keyed by (token, start): a backfilled minute that already exists is ignored, so nothing is counted twice.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

from app.live import calendar
from app.live.tick import Tick

UTC = calendar.UTC
IST = calendar.IST
MINUTE = dt.timedelta(minutes=1)
CLOSE_DELAY = dt.timedelta(seconds=2)
TFS = {"5m": dt.timedelta(minutes=5), "15m": dt.timedelta(minutes=15), "1d": None}


@dataclass(slots=True)
class Candle:
    token: str
    symbol: str
    exchange: str
    tf: str
    start: dt.datetime          # aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    source: str = "live"

    @property
    def key(self) -> tuple[str, str, dt.datetime]:
        return (self.token, self.tf, self.start)


def floor_minute(t: dt.datetime) -> dt.datetime:
    return t.astimezone(UTC).replace(second=0, microsecond=0)


class CandleBuilder:
    """Ticks -> closed 1-minute candles."""

    def __init__(self) -> None:
        self._cur: dict[str, Candle] = {}
        self._cum: dict[str, int] = {}
        self.late_ticks = 0

    def on_tick(self, t: Tick) -> list[Candle]:
        minute = floor_minute(t.exchange_ts)
        closed: list[Candle] = []
        cur = self._cur.get(t.key)
        if cur is not None and minute > cur.start:
            closed.append(cur)
            cur = None
        elif cur is not None and minute < cur.start:
            self.late_ticks += 1               # an older minute is already closed (or about to be): never rewrite history
            return closed
        dv = 0
        prev = self._cum.get(t.key)
        if prev is not None and t.volume >= prev:
            dv = t.volume - prev
        self._cum[t.key] = t.volume
        if cur is None:
            self._cur[t.key] = Candle(t.token, t.symbol, t.exchange, "1m", minute, t.ltp, t.ltp, t.ltp, t.ltp, dv)
        else:
            cur.high, cur.low, cur.close = max(cur.high, t.ltp), min(cur.low, t.ltp), t.ltp
            cur.volume += dv
        return closed

    def flush(self, now: dt.datetime) -> list[Candle]:
        """Close every open minute that ended at least 2 s before `now`."""
        now = now.astimezone(UTC)
        out = []
        for key, c in list(self._cur.items()):
            if now >= c.start + MINUTE + CLOSE_DELAY:
                out.append(self._cur.pop(key))
        return out

    def open_candles(self) -> list[Candle]:
        return list(self._cur.values())


class Aggregator:
    """Closed 1m candles -> closed 5m / 15m / 1d candles."""

    def __init__(self, tfs: tuple[str, ...] = ("5m", "15m", "1d")) -> None:
        self.tfs = tfs
        self._minutes: dict[str, dict[dt.datetime, Candle]] = {}
        self._pending: dict[str, dict[tuple[str, dt.datetime], dt.datetime]] = {}   # token key -> {(tf, bucket start): bucket end}
        self._emitted: set[tuple[str, str, dt.datetime]] = set()
        self._latest: dict[str, dt.datetime] = {}

    def add_minute(self, c: Candle) -> bool:
        """Remember a closed minute. False when that minute is already known (a duplicate or an overlapping backfill)."""
        k = f"{c.exchange}:{c.token}"
        d = self._minutes.setdefault(k, {})
        if c.start in d:
            return False
        d[c.start] = c
        if k not in self._latest or c.start > self._latest[k]:
            self._latest[k] = c.start
        for tf in self.tfs:
            bk = self.bucket(c.exchange, c.start, tf)
            if bk and (k, tf, bk[0]) not in self._emitted:
                self._pending.setdefault(k, {})[(tf, bk[0])] = bk[1]
        return True

    @staticmethod
    def bucket(exchange: str, start: dt.datetime, tf: str) -> tuple[dt.datetime, dt.datetime] | None:
        """(bucket start, bucket end) of the bucket this minute falls in, clipped to the session."""
        day = start.astimezone(IST).date()
        b = calendar.session_bounds(exchange, day)
        if b is None:
            return None
        s_open, s_close = b
        if tf == "1d":
            return s_open, s_close
        width = TFS[tf]
        n = max(0, int((start - s_open) / width))
        bs = s_open + n * width
        return bs, min(bs + width, s_close)

    def sweep(self, now: dt.datetime) -> list[Candle]:
        """Closed higher-timeframe candles that became complete: a later minute exists, or the bucket ended 2 s ago."""
        now = now.astimezone(UTC)
        out: list[Candle] = []
        for k, pend in self._pending.items():
            latest = self._latest[k]
            mins = self._minutes[k]
            for (tf, bs), be in list(pend.items()):
                if not (latest >= be or now >= be + CLOSE_DELAY):
                    continue
                cs = []
                t = bs
                while t < be:
                    if t in mins:
                        cs.append(mins[t])
                    t += MINUTE
                del pend[(tf, bs)]
                if not cs:
                    continue
                f = cs[0]
                out.append(Candle(f.token, f.symbol, f.exchange, tf, bs, f.open, max(x.high for x in cs), min(x.low for x in cs),
                                  cs[-1].close, sum(x.volume for x in cs), f.source))
                self._emitted.add((k, tf, bs))
        out.sort(key=lambda c: (c.start, c.tf))
        return out

    def forget_before(self, cutoff: dt.datetime) -> None:
        """Drop minutes older than `cutoff` (memory); anything already emitted stays emitted."""
        for mins in self._minutes.values():
            for s in [s for s in mins if s < cutoff]:
                del mins[s]
        self._emitted = {e for e in self._emitted if e[2] >= cutoff}


@dataclass
class History:
    """Rolling window of closed candles per (token, tf) for strategies."""

    size: int = 500
    data: dict[tuple[str, str], list[Candle]] = field(default_factory=dict)

    def push(self, c: Candle) -> list[Candle]:
        lst = self.data.setdefault((f"{c.exchange}:{c.token}", c.tf), [])
        if lst and lst[-1].start >= c.start:
            return lst
        lst.append(replace(c))
        if len(lst) > self.size:
            del lst[: len(lst) - self.size]
        return lst
