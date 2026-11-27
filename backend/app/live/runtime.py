"""Process-wide handles of the live pipeline, importable from anywhere without a circular import.

`store` always exists (it is simply empty until ticks arrive), so pricing / API code can ask it unconditionally; `pipeline` is None when the
pipeline is not running (tests, FEED_MODE=off)."""
from __future__ import annotations

from app.live.core import Clock, LatestPriceStore
from app.live.tick import Tick

clock = Clock()
store = LatestPriceStore(clock)
pipeline = None          # type: ignore[assignment]  # app.live.pipeline.Pipeline once started


def fresh_tick(exchange: str, token: str, max_age: float = 3.0) -> Tick | None:
    """The pushed price if it is at most `max_age` seconds old, else None."""
    t = store.get(exchange, token)
    a = store.age(exchange, token)
    return t if t is not None and a is not None and a <= max_age else None


def feed_connected() -> bool:
    return bool(pipeline and pipeline.receiver and pipeline.receiver.connected)


def untrusted(exchange: str, token: str) -> bool:
    """True when the stored price is STALE (market open, quiet > 60 s) AND the feed itself is down: then nothing may be filled on it."""
    return store.is_stale(exchange, token) and not feed_connected()


def notify_user(user_id: int, message: dict) -> None:
    """Thread-safe: tell a user's open browser tabs that orders / positions changed."""
    if pipeline is not None:
        pipeline.push_event(user_id, message)


def touch(specs: list[tuple[str, str]]) -> None:
    """Someone is looking at these tokens: keep them subscribed for a while."""
    if pipeline is not None:
        pipeline.touch(specs)
