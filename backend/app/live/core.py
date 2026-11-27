"""Clock, latest-price store and the tick bus."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from app.live import calendar
from app.live.tick import Tick

log = logging.getLogger(__name__)
UTC = calendar.UTC

STALE_AFTER_S = 60.0


class Clock:
    """Wall clock, or a virtual one that a replay moves with the exchange timestamps."""

    def __init__(self) -> None:
        self._virtual: dt.datetime | None = None

    def now(self) -> dt.datetime:
        return self._virtual or dt.datetime.now(UTC)

    def set(self, t: dt.datetime) -> None:
        if self._virtual is None or t > self._virtual:
            self._virtual = t.astimezone(UTC)

    def use_real(self) -> None:
        self._virtual = None

    @property
    def virtual(self) -> bool:
        return self._virtual is not None


class LatestPriceStore:
    """token -> last Tick and the clock time it arrived. A symbol is STALE when its exchange is open and it has been quiet for > 60 s."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self._ticks: dict[str, Tick] = {}
        self._at: dict[str, dt.datetime] = {}
        self.last_update: dt.datetime | None = None

    def update(self, t: Tick) -> None:
        self._ticks[t.key] = t
        self.last_update = self._at[t.key] = self.clock.now()

    def get(self, exchange: str, token: str) -> Tick | None:
        return self._ticks.get(f"{exchange}:{token}")

    def age(self, exchange: str, token: str) -> float | None:
        at = self._at.get(f"{exchange}:{token}")
        return None if at is None else (self.clock.now() - at).total_seconds()

    def state(self, exchange: str, token: str) -> str:
        """live | stale | closed (market shut: silence is normal) | unknown (never ticked)."""
        a = self.age(exchange, token)
        if a is None:
            return "unknown"
        if not calendar.is_open(exchange, self.clock.now()):
            return "closed"
        return "stale" if a > STALE_AFTER_S else "live"

    def is_stale(self, exchange: str, token: str) -> bool:
        return self.state(exchange, token) == "stale"

    def last_tick_age_by_exchange(self) -> dict[str, float | None]:
        now = self.clock.now()
        out: dict[str, float | None] = {}
        for k, at in self._at.items():
            ex = k.split(":")[0]
            a = (now - at).total_seconds()
            out[ex] = a if ex not in out or out[ex] is None or a < out[ex] else out[ex]
        return out


@dataclass
class _Sub:
    q: asyncio.Queue
    drop_oldest: bool


class Bus:
    """One producer, many consumers. `publish` never blocks the producer:
    - critical queues (candles, orders, persistence) are unbounded: nothing is ever dropped, a backlog only shows up in /health;
    - the UI queue is bounded and drops its OLDEST item when full (a screen only needs the newest price)."""

    def __init__(self) -> None:
        self._subs: dict[str, list[_Sub]] = defaultdict(list)
        self.dropped_ui = 0
        self.published = 0

    def subscribe(self, topic: str, maxsize: int = 0, drop_oldest: bool = False) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs[topic].append(_Sub(q, drop_oldest))
        return q

    def publish(self, topic: str, item) -> None:
        self.published += 1
        for s in self._subs[topic]:
            if s.drop_oldest and s.q.maxsize and s.q.full():
                try:
                    s.q.get_nowait()
                    s.q.task_done()
                    self.dropped_ui += 1
                except asyncio.QueueEmpty:
                    pass
            s.q.put_nowait(item)

    def sizes(self) -> dict[str, list[int]]:
        return {t: [s.q.qsize() for s in subs] for t, subs in self._subs.items()}

    def queues(self) -> list[asyncio.Queue]:
        return [s.q for subs in self._subs.values() for s in subs]


def now_s() -> float:
    return time.time()
