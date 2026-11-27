"""Tick replay: push a recorded tick file through the whole pipeline, no broker and no live market needed.

A tick file is JSON Lines, one RAW websocket message per line, exactly what the receiver records when RECORD_TICKS=/path/ticks.jsonl is set:
    {"subscription_mode": 2, "exchange_type": 1, "token": "\\"2885\\"", "last_traded_price": 139450, "exchange_timestamp": 1795763441000,
     "volume_trade_for_the_day": 123456}
The pipeline's clock becomes virtual and follows the exchange timestamps, so candles close, buckets sweep and the EOD square-off fires exactly as
they would have on the day, however fast the file is replayed.

  speed 0  = as fast as possible (tests, CI)        speed 1 = real time        speed 10 = ten times faster
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging

from app.live import calendar

log = logging.getLogger("live.replay")
UTC = calendar.UTC


def read_ticks(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    out.sort(key=lambda r: r.get("exchange_timestamp", 0))
    return out


async def play(pipeline, path_or_ticks, speed: float = 0.0, advance_every: int = 200) -> dict:
    ticks = read_ticks(path_or_ticks) if isinstance(path_or_ticks, str) else list(path_or_ticks)
    if not ticks:
        return {"ticks": 0}
    first = dt.datetime.fromtimestamp(ticks[0]["exchange_timestamp"] / 1000, UTC)
    pipeline.clock.set(first)
    prev = ticks[0]["exchange_timestamp"]
    last = first
    for i, raw in enumerate(ticks, 1):
        ts = raw["exchange_timestamp"]
        if speed > 0 and ts > prev:
            await asyncio.sleep((ts - prev) / 1000.0 / speed)
        prev = ts
        await pipeline.feed_raw(raw)
        if i % advance_every == 0:
            await pipeline.drain()
            last = dt.datetime.fromtimestamp(ts / 1000, UTC)
            await pipeline.advance(last)
    await pipeline.drain()
    last = dt.datetime.fromtimestamp(ticks[-1]["exchange_timestamp"] / 1000, UTC)
    end_of_minute = last.replace(second=0, microsecond=0) + dt.timedelta(minutes=1, seconds=2)
    await pipeline.advance(end_of_minute)                        # close the minute that was still open (M+1:00 + 2 s)
    await pipeline.drain()
    log.info("replay finished: %s ticks", len(ticks))
    return {"ticks": len(ticks), "first": first.isoformat(), "last": last.isoformat()}
