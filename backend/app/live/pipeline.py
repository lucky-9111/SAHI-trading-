"""The live market-data pipeline.

    Receiver (thread) --raw--> raw_q --Normalizer--> Tick --> LatestPriceStore
                                                        |
                                                        +--> Bus topic "tick" --> candle task   (unbounded)  -> closed 1m / 5m / 15m / 1d candles
                                                        |                    --> orders task   (unbounded)  -> paper engine (limit, stop, target)
                                                        |                    --> ui queue      (bounded, drop-oldest) -> /ws/ticks
    candle task --> Bus topic "candle" --> writer task (DB, unbounded) / strategy task (signals -> paper orders) / ui events
    timer task (1 Hz) --> flush quiet minutes, sweep buckets, EOD square-off, subscription sync, feed status, daily jobs

Every handler that touches the database runs through asyncio.to_thread, so a slow disk can never stall the loop that reads the socket.
One tick producer, many consumers; only the UI queue ever drops anything.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Callable

from app.database.session import SessionLocal
from app.live import calendar, paper, repo, runtime
from app.live.candles import Aggregator, Candle, CandleBuilder, History
from app.live.core import Bus, Clock, LatestPriceStore
from app.live.receiver import Receiver
from app.live.strategy import StrategyRunner, place_signal
from app.live.tick import Normalizer, Tick

log = logging.getLogger("live")
UTC, IST = calendar.UTC, calendar.IST

# index tokens are not in the instrument table; the REST API already knows them
INDEX_TOKENS = {("NSE", "99926000"): "NIFTY50", ("NSE", "99926009"): "BANKNIFTY", ("BSE", "99919000"): "SENSEX",
                ("NSE", "99926037"): "FINNIFTY", ("NSE", "99926074"): "MIDCPNIFTY"}
INTEREST_TTL_S = 120.0
BACKFILL_MAX_TOKENS = 30


class Pipeline:
    def __init__(self, mode: str = "live", clock: Clock | None = None, store: LatestPriceStore | None = None, fetcher=repo.broker_fetcher,
                 persist: bool = True, check_session: bool = True, session_factory=SessionLocal, receiver_factory: Callable | None = None,
                 timers: bool = True) -> None:
        self.mode = mode
        self.clock = clock or runtime.clock
        self.store = store or runtime.store
        self.fetcher = fetcher
        self.persist = persist
        self.session_factory = session_factory
        self.timers = timers
        self.index: dict[str, tuple[int | None, str]] = {f"{e}:{t}": (None, s) for (e, t), s in INDEX_TOKENS.items()}
        self.bus = Bus()
        self.norm = Normalizer(self.symbol_of, check_session)
        self.builder = CandleBuilder()
        self.aggregator = Aggregator()
        self.history = History()
        self.runner = StrategyRunner(self.history)
        self.raw_q: asyncio.Queue = asyncio.Queue()
        self.q_candle_ticks = self.bus.subscribe("tick")
        self.q_orders = self.bus.subscribe("tick")
        self.ui_q = self.bus.subscribe("tick", maxsize=2000, drop_oldest=True)
        self.q_writer = self.bus.subscribe("candle")
        self.q_strategy = self.bus.subscribe("candle")
        self.q_events = self.bus.subscribe("event", maxsize=2000, drop_oldest=True)
        self._interest: dict[tuple[str, str], float] = {}
        self._armed: dict[str, list[int]] = {}
        self._cursor = dt.datetime.min.replace(tzinfo=UTC)         # stream time seen by the candle task (replay)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        self._last = {"armed": 0.0, "sync": 0.0, "eod": 0.0, "status": 0.0, "daily": ""}
        self.errors = 0
        self.last_candle: Candle | None = None
        self.ticks_in = 0
        self.receiver: Receiver | None = None
        if mode == "live":
            from app.market_data.angel import AngelProvider

            if receiver_factory is not None or AngelProvider.configured():
                self.receiver = (receiver_factory or Receiver)(self._from_thread, self._reconnected)
            else:
                log.warning("Angel One credentials are not set: the live feed is off")

    # ------------------------------------------------------------------ ingestion
    def symbol_of(self, exchange: str, token: str) -> str | None:
        e = self.index.get(f"{exchange}:{token}")
        return e[1] if e else None

    def _from_thread(self, raw: dict) -> None:
        """Called on the SDK thread: only a thread-safe hand-off onto the loop."""
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self.raw_q.put_nowait, (time.time(), raw))

    async def feed_raw(self, raw: dict, received_ts: float | None = None) -> None:
        await self.raw_q.put((received_ts or time.time(), raw))

    def _reconnected(self, _ok: bool) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: self._spawn(self.backfill_all()))

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        from app.live import logs

        logs.configure()
        self._loop = asyncio.get_running_loop()
        n = self.clock.now().astimezone(IST)                  # a restart after 08:30 / 08:50 must not repeat today's daily jobs
        day = n.date().isoformat()
        self._last["daily"] = day + "b" if n.time() >= dt.time(8, 50) else day + "a" if n.time() >= dt.time(8, 30) else ""
        await asyncio.to_thread(self.load_index)
        coros = [self._normalize_loop(), self._candle_loop(), self._orders_loop(), self._writer_loop(), self._strategy_loop()]
        if self.timers:
            coros.append(self._timer_loop())
        for c in coros:
            self._spawn(c)
        if self.receiver:
            self.receiver.start()
            await self.sync_subscriptions()
            self._spawn(self.backfill_all())
        log.info("pipeline started (mode=%s)", self.mode)

    async def stop(self) -> None:
        if self.receiver:
            self.receiver.stop()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.ensure_future(coro)
        self._tasks.append(t)
        return t

    def load_index(self) -> None:
        """All instruments token -> (id, symbol), so the normalizer can name a token without touching the database per tick."""
        from sqlalchemy import select

        from app.models.market import Instrument

        with self.session_factory() as db:
            rows = db.execute(select(Instrument.id, Instrument.exchange, Instrument.token, Instrument.symbol)).all()
        idx = {f"{e}:{t}": (i, s) for i, e, t, s in rows}
        for (e, t), s in INDEX_TOKENS.items():
            idx.setdefault(f"{e}:{t}", (None, s))
        self.index = idx
        log.info("instrument index loaded: %s tokens", len(idx))

    async def drain(self) -> None:
        """Wait until every queue is empty and every handler has finished (replays and tests)."""
        mine = (self.q_candle_ticks, self.q_orders, self.q_writer, self.q_strategy)    # the UI queues belong to the websocket manager
        for _ in range(3):
            await self.raw_q.join()
            for q in mine:
                await q.join()

    # ------------------------------------------------------------------ interest / subscriptions
    def touch(self, specs: list[tuple[str, str]]) -> None:
        exp = time.time() + INTEREST_TTL_S
        for s in specs:
            self._interest[s] = exp

    def wanted(self) -> set[tuple[str, str]]:
        now = time.time()
        self._interest = {k: e for k, e in self._interest.items() if e > now}
        w = set(self._interest)
        try:
            w |= paper.open_position_tokens(self.session_factory)
            w |= self.runner.refresh(self.clock.now())
        except Exception:  # noqa: BLE001
            self.errors += 1
            log.exception("could not compute the wanted tokens")
        return w

    async def sync_subscriptions(self) -> None:
        if self.receiver:
            w = await asyncio.to_thread(self.wanted)
            self.receiver.set_wanted(w)

    # ------------------------------------------------------------------ consumers
    async def _normalize_loop(self) -> None:
        while True:
            recv, raw = await self.raw_q.get()
            try:
                t = self.norm(raw, recv)
                if t is not None:
                    self.ticks_in += 1
                    if self.clock.virtual or self.mode == "replay":
                        self.clock.set(t.utc)
                    self.store.update(t)
                    self.bus.publish("tick", t)
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("normalizer failed", extra={"stage": "normalize"})
            finally:
                self.raw_q.task_done()

    def stream_now(self) -> dt.datetime:
        return self._cursor if (self.clock.virtual or self.mode == "replay") else self.clock.now()

    async def _candle_loop(self) -> None:
        while True:
            t: Tick = await self.q_candle_ticks.get()
            try:
                if t.utc > self._cursor:
                    self._cursor = t.utc
                self._minutes_closed(self.builder.on_tick(t))
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("candle builder failed", extra={"token": t.token, "symbol": t.symbol, "stage": "candles"})
            finally:
                self.q_candle_ticks.task_done()

    def _minutes_closed(self, closed: list[Candle]) -> None:
        for c in closed:
            if self.aggregator.add_minute(c):
                self._emit(c)
        for h in self.aggregator.sweep(self.stream_now()):
            self._emit(h)

    def _emit(self, c: Candle) -> None:
        self.last_candle = c
        self.history.push(c)
        self.bus.publish("candle", c)

    async def _orders_loop(self) -> None:
        while True:
            t: Tick = await self.q_orders.get()
            try:
                for iid in self._armed.get(t.key, ()):
                    events, users = await asyncio.to_thread(paper.on_tick, iid, t.ltp, self.session_factory)
                    if events:
                        log.info("paper engine: %s", "; ".join(events), extra={"token": t.token, "symbol": t.symbol, "stage": "orders"})
                        self._notify(users, {"type": "orders_changed", "symbol": t.symbol, "events": events})
                        self._last["armed"] = 0.0           # something filled or closed: re-arm on the next timer pass
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("paper engine failed", extra={"token": t.token, "symbol": t.symbol, "stage": "orders"})
            finally:
                self.q_orders.task_done()

    async def _writer_loop(self) -> None:
        while True:
            batch = [await self.q_writer.get()]
            while not self.q_writer.empty() and len(batch) < 500:
                batch.append(self.q_writer.get_nowait())
            try:
                if self.persist:
                    await asyncio.to_thread(repo.upsert_candles, batch, self.session_factory)
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("candle write failed", extra={"stage": "writer"})
            finally:
                for _ in batch:
                    self.q_writer.task_done()

    async def _strategy_loop(self) -> None:
        while True:
            c: Candle = await self.q_strategy.get()
            try:
                for b, sig, candle in self.runner.on_candle(c):
                    res = await asyncio.to_thread(place_signal, b, sig, candle, self.session_factory)
                    log.info("signal %s %s %s -> %s (%s)", b.strategy.name, sig.side, candle.symbol, res, sig.reason,
                             extra={"token": candle.token, "symbol": candle.symbol, "stage": "strategy"})
                    self._last["armed"] = 0.0
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("strategy task failed", extra={"stage": "strategy"})
            finally:
                self.q_strategy.task_done()

    # ------------------------------------------------------------------ timers
    async def _timer_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                await self.advance(self.clock.now())
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("timer failed", extra={"stage": "timer"})

    async def advance(self, now: dt.datetime) -> None:
        """What the 1 Hz timer does. A replay calls it with the virtual time instead."""
        if self.clock.virtual or self.mode == "replay":
            if now > self._cursor:
                self._cursor = now
        self._minutes_closed(self.builder.flush(now))
        t = time.monotonic()
        if t - self._last["armed"] >= 2.0:
            self._last["armed"] = t
            armed = await asyncio.to_thread(paper.armed, self.session_factory)
            m: dict[str, list[int]] = {}
            for iid, (ex, tok) in armed.items():
                m.setdefault(f"{ex}:{tok}", []).append(iid)
            self._armed = m
        if t - self._last["eod"] >= 5.0:
            self._last["eod"] = t
            ev, users = await asyncio.to_thread(paper.square_off_intraday, now, self._price_of, self.session_factory)
            if ev:
                log.info("EOD: %s", "; ".join(ev), extra={"stage": "orders"})
                self._notify(users, {"type": "orders_changed", "events": ev})
        if self.receiver and t - self._last["sync"] >= 5.0:
            self._last["sync"] = t
            await self.sync_subscriptions()
        if t - self._last["status"] >= 5.0:
            self._last["status"] = t
            self.bus.publish("event", {"type": "feed", **self.feed_status()})
        await self._daily(now)

    def _price_of(self, exchange: str, token: str) -> float | None:
        tk = self.store.get(exchange, token)
        if tk is not None:
            return tk.ltp
        try:
            from app.trading import pricing
            from app.models.market import Instrument
            from sqlalchemy import select

            with self.session_factory() as db:
                inst = db.scalar(select(Instrument).where(Instrument.exchange == exchange, Instrument.token == token))
                return float(pricing.get_price(inst, max_age=0).price) if inst else None
        except Exception:  # noqa: BLE001
            return None

    async def _daily(self, now: dt.datetime) -> None:
        """08:30 IST instrument master + rollover, 08:50 broker session refresh. Once per day each; never when replaying."""
        if self.mode != "live" or self.clock.virtual:
            return
        n = now.astimezone(IST)
        day = n.date().isoformat()
        if n.time() >= dt.time(8, 30) and self._last["daily"] < day + "a":
            self._last["daily"] = day + "a"
            await asyncio.to_thread(self._refresh_master)
        if n.time() >= dt.time(8, 50) and self._last["daily"] < day + "b":
            self._last["daily"] = day + "b"
            from app.market_data import angel

            angel.provider.refresh()
            log.info("broker session refreshed before the open")

    def _refresh_master(self) -> None:
        try:
            from app.market_data import instrument_master as im

            im.sync_from_provider()
            self.load_index()
            self.runner.refresh(self.clock.now())            # a future that expired: the strategy follows next month's contract
        except Exception:  # noqa: BLE001
            self.errors += 1
            log.exception("instrument master refresh failed", extra={"stage": "master"})

    # ------------------------------------------------------------------ backfill
    async def backfill_token(self, exchange: str, token: str, now: dt.datetime | None = None) -> int:
        """Fill today's missing 1-minute candles of one token from the historical API; live candles already known are never replaced."""
        now = now or self.clock.now()
        symbol = self.symbol_of(exchange, token) or token
        b = calendar.session_bounds(exchange, now.astimezone(IST).date())
        if b is None:
            return 0
        known = {c.start for c in self.aggregator._minutes.get(f"{exchange}:{token}", {}).values()}
        if self.persist:
            known |= await asyncio.to_thread(repo.minute_starts, exchange, token, b[0], self.session_factory)
        try:
            new = await asyncio.to_thread(repo.backfill_minutes, exchange, token, symbol, known, now, self.fetcher)
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            log.warning("backfill failed for %s: %s", symbol, e, extra={"token": token, "symbol": symbol, "stage": "backfill"})
            return 0
        added = 0
        for c in new:
            if self.aggregator.add_minute(c):
                self._emit(c)
                added += 1
        for h in self.aggregator.sweep(self.stream_now()):
            self._emit(h)
        if added:
            log.info("backfilled %s minutes for %s", added, symbol, extra={"token": token, "symbol": symbol, "stage": "backfill"})
        return added

    async def backfill_all(self) -> None:
        w = sorted(await asyncio.to_thread(self.wanted))[:BACKFILL_MAX_TOKENS]
        for ex, tok in w:
            await self.backfill_token(ex, tok)

    # ------------------------------------------------------------------ events / health
    def push_event(self, user_id: int, msg: dict) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self.bus.publish, "event", {**msg, "user_id": user_id})

    def _notify(self, users: set[int], msg: dict) -> None:
        for u in users:
            self.bus.publish("event", {**msg, "user_id": u})

    def feed_status(self) -> dict:
        """connected | stale | reconnecting | closed | replay"""
        if self.mode == "replay":
            return {"state": "replay", "last_tick_age_s": None}
        r = self.receiver
        ages = self.store.last_tick_age_by_exchange()
        newest = min([a for a in ages.values() if a is not None], default=None)
        anyopen = any(calendar.is_open(ex) for ex in {e for e, _ in (r._wanted if r else set())})
        if r is None or not r.connected:
            state = "reconnecting" if (r and r.reconnects) or (r and anyopen) else "closed"
        elif anyopen and r._wanted and (newest is None or newest > 20):
            state = "stale"
        else:
            state = "connected"
        return {"state": state, "last_tick_age_s": None if newest is None else round(newest, 1)}

    def health(self) -> dict:
        r = self.receiver
        return {
            "feed": {**self.feed_status(), **(r.status() if r else {"connected": False})},
            "mode": self.mode,
            "last_tick_age_by_exchange_s": {k: (None if v is None else round(v, 1)) for k, v in self.store.last_tick_age_by_exchange().items()},
            "queues": {"raw": self.raw_q.qsize(), **{t: s for t, s in self.bus.sizes().items()}},
            "ui_dropped": self.bus.dropped_ui,
            "last_candle_closed": None if not self.last_candle else {
                "symbol": self.last_candle.symbol, "tf": self.last_candle.tf, "start": self.last_candle.start.isoformat()},
            "ticks_in": self.ticks_in,
            "dropped_ticks": self.norm.dropped,
            "late_ticks": self.builder.late_ticks,
            "strategy": {"bindings": len(self.runner.bindings), "signals": self.runner.signals, "errors": self.runner.errors},
            "error_count": self.errors,
        }
