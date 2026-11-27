"""Browser push: WebSocket /ws/ticks.

Client -> server (JSON):  {"op":"subscribe","symbols":["NSE:2885","MCX:495213"]}   {"op":"unsubscribe","symbols":[...]}
Server -> client:         {"type":"tick","k":"NSE:2885","ltp":1394.5,"ts":..., "state":"live|stale|closed"}   (at most ~4 per symbol per second)
                          {"type":"feed","state":"connected|stale|reconnecting|closed|replay","last_tick_age_s":..}
                          {"type":"orders_changed","events":[...]}   (a fill / stop / target / square-off touched this user)
Auth: the same JWT as the REST API, passed as ?token=... (browsers cannot set headers on a WebSocket).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.live import runtime
from app.live.tick import TYPE_BY_EXCHANGE

log = logging.getLogger(__name__)
router = APIRouter()
FLUSH_S = 0.25            # 4 updates / second / symbol at most
MAX_SUBS = 80


@dataclass(eq=False)
class Client:
    ws: WebSocket
    user_id: int
    subs: set[str] = field(default_factory=set)
    sent: dict[str, float] = field(default_factory=dict)


class Manager:
    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self.latest: dict[str, tuple] = {}              # key -> (ltp, exchange_ts_ms, state)
        self._dirty: set[str] = set()
        self._tasks: list[asyncio.Task] = []

    def start(self, pipeline) -> None:
        self._tasks = [asyncio.ensure_future(self._pump_ticks(pipeline)), asyncio.ensure_future(self._pump_events(pipeline)),
                       asyncio.ensure_future(self._flusher()), asyncio.ensure_future(self._touch(pipeline))]

    def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def _pump_ticks(self, pipeline) -> None:
        while True:
            t = await pipeline.ui_q.get()
            self.latest[t.key] = (t.ltp, int(t.exchange_ts.timestamp() * 1000), None)
            self._dirty.add(t.key)
            pipeline.ui_q.task_done()

    async def _pump_events(self, pipeline) -> None:
        while True:
            ev = await pipeline.q_events.get()
            try:
                uid = ev.pop("user_id", None)
                for c in list(self.clients):
                    if uid is None or c.user_id == uid:
                        await self._send(c, ev)
            finally:
                pipeline.q_events.task_done()

    async def _touch(self, pipeline) -> None:
        while True:
            await asyncio.sleep(30)
            pipeline.touch([tuple(k.split(":", 1)) for c in self.clients for k in c.subs])

    async def _flusher(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_S)
            if not self._dirty:
                continue
            dirty, self._dirty = self._dirty, set()
            for c in list(self.clients):
                for k in dirty & c.subs:
                    ltp, ts, _ = self.latest[k]
                    ex, tok = k.split(":", 1)
                    await self._send(c, {"type": "tick", "k": k, "ltp": ltp, "ts": ts, "state": runtime.store.state(ex, tok)})

    async def _send(self, c: Client, msg: dict) -> None:
        try:
            await c.ws.send_text(json.dumps(msg))
        except Exception:  # noqa: BLE001
            self.clients.discard(c)


manager = Manager()


def _valid(sym: str) -> bool:
    ex, _, tok = sym.partition(":")
    return ex in TYPE_BY_EXCHANGE and tok.isalnum()


@router.websocket("/ws/ticks")
async def ticks_ws(ws: WebSocket, token: str = "") -> None:
    uid = decode_access_token(token)
    if not uid:
        await ws.close(code=4401)
        return
    await ws.accept()
    c = Client(ws, uid)
    manager.clients.add(c)
    pl = runtime.pipeline
    await manager._send(c, {"type": "feed", **(pl.feed_status() if pl else {"state": "closed", "last_tick_age_s": None})})
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            syms = [s for s in msg.get("symbols", []) if isinstance(s, str) and _valid(s)]
            if msg.get("op") == "subscribe":
                c.subs |= set(syms[: max(0, MAX_SUBS - len(c.subs))])
                if pl:
                    pl.touch([tuple(s.split(":", 1)) for s in syms])
                for s in syms:                                  # first paint: the price we already have, without waiting for the next tick
                    ex, tok = s.split(":", 1)
                    t = runtime.store.get(ex, tok)
                    if t is not None and s in c.subs:
                        await manager._send(c, {"type": "tick", "k": s, "ltp": t.ltp, "ts": int(t.exchange_ts.timestamp() * 1000),
                                                "state": runtime.store.state(ex, tok)})
            elif msg.get("op") == "unsubscribe":
                c.subs -= set(syms)
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        manager.clients.discard(c)
