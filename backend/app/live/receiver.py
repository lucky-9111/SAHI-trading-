"""Stage 1 of the pipeline: the Angel One websocket (SmartWebSocketV2).

The receiver lives in its own thread. Its only jobs: keep ONE connection alive, subscribe the wanted tokens (QUOTE mode, grouped by exchange),
and hand every raw message to `on_raw` (which does a thread-safe `loop.call_soon_threadsafe(queue.put_nowait, ...)`). No parsing beyond what the
SDK already does, no database, no business logic in the callback.

Reliability:
* heartbeat: while any wanted exchange is open, silence longer than `stall_s` means the feed is dead -> close and reconnect;
  outside market hours silence is normal and is never treated as a failure;
* reconnect with exponential backoff 1, 2, 4 ... 30 s (reset once a connection delivered data), then every wanted token is subscribed again;
* every connect / disconnect / reconnect and the number of subscribed tokens are logged; secrets never are.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable

from app.core.config import get_settings
from app.live import calendar
from app.live.tick import TYPE_BY_EXCHANGE

log = logging.getLogger(__name__)

QUOTE_MODE = 2                     # carries last price + cumulative volume (LTP mode has no volume)
MAX_TOKENS = int(os.environ.get("FEED_MAX_TOKENS", "500"))
STALL_S = float(os.environ.get("FEED_STALL_SECONDS", "20"))
BACKOFF = (1, 2, 4, 8, 16, 30)


class Receiver:
    def __init__(self, on_raw: Callable[[dict], None], on_connect: Callable[[bool], None] | None = None,
                 client_factory: Callable | None = None, record_path: str | None = None, stall_s: float = STALL_S, watch_s: float = 2.0) -> None:
        self.on_raw = on_raw
        self.on_connect = on_connect                       # called with True after a RE-connect (the pipeline backfills the gap)
        self._client_factory = client_factory              # tests: returns an object with the SmartWebSocketV2 surface
        self.record_path = record_path or os.environ.get("RECORD_TICKS")
        self.stall_s = stall_s
        self.watch_s = watch_s
        self._wanted: set[tuple[str, str]] = set()
        self._subscribed: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._sws = None
        self._thread: threading.Thread | None = None
        self._dog: threading.Thread | None = None
        self._stop = threading.Event()
        self.connected = False
        self.reconnects = 0
        self.last_msg_at = 0.0
        self.last_error: str | None = None
        self.messages = 0
        self._rec = None

    # ---------------- public ----------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="tick-receiver")
        self._thread.start()
        self._dog = threading.Thread(target=self._watch, daemon=True, name="tick-watchdog")
        self._dog.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_socket()

    def set_wanted(self, wanted: set[tuple[str, str]]) -> None:
        """The full set of (exchange, token) that should be subscribed; the difference is applied on the open socket."""
        wanted = {w for w in wanted if w[0] in TYPE_BY_EXCHANGE}
        if len(wanted) > MAX_TOKENS:
            log.warning("feed: %s tokens wanted, the limit is %s; the extra ones are not subscribed", len(wanted), MAX_TOKENS)
            wanted = set(sorted(wanted)[:MAX_TOKENS])
        with self._lock:
            self._wanted = wanted
        if self.connected:
            self._apply()

    def status(self) -> dict:
        age = (time.time() - self.last_msg_at) if self.last_msg_at else None
        return {"connected": self.connected, "reconnects": self.reconnects, "subscribed": len(self._subscribed), "wanted": len(self._wanted),
                "last_message_age_s": None if age is None else round(age, 1), "messages": self.messages, "error": self.last_error}

    # ---------------- internals ----------------
    def _group(self, pairs) -> list[dict]:
        g: dict[int, list[str]] = {}
        for ex, tok in pairs:
            g.setdefault(TYPE_BY_EXCHANGE[ex], []).append(tok)
        return [{"exchangeType": t, "tokens": toks} for t, toks in g.items()]

    def _apply(self) -> None:
        with self._lock:
            add, drop = self._wanted - self._subscribed, self._subscribed - self._wanted
        sws = self._sws
        if sws is None:
            return
        try:
            if add:
                sws.subscribe("sahi%06d" % (int(time.time()) % 10**6), QUOTE_MODE, self._group(add))
            if drop:
                sws.unsubscribe("sahi%06d" % (int(time.time()) % 10**6), QUOTE_MODE, self._group(drop))
            with self._lock:
                self._subscribed = (self._subscribed | add) - drop
            if add or drop:
                log.info("feed: subscribed %s tokens (+%s -%s)", len(self._subscribed), len(add), len(drop))
        except Exception as e:  # noqa: BLE001
            self.last_error = f"subscribe failed: {type(e).__name__}"
            log.warning("feed: %s", self.last_error)

    def _close_socket(self) -> None:
        try:
            if self._sws is not None:
                self._sws.close_connection()
        except Exception:  # noqa: BLE001
            pass

    def _make_client(self):
        if self._client_factory:
            return self._client_factory()
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        from app.market_data import angel

        client = angel.provider.session()
        s = get_settings()
        return SmartWebSocketV2(client.access_token, s.angel_api_key, s.angel_client_code, client.getfeedToken(), max_retry_attempt=0)

    def _handle(self, _ws, message) -> None:
        # called on the SDK thread: stamp, record, hand off. Nothing else.
        self.last_msg_at = time.time()
        self.messages += 1
        if isinstance(message, dict):
            if self._rec:
                try:
                    self._rec.write(json.dumps(message) + "\n")
                except Exception:  # noqa: BLE001
                    pass
            self.on_raw(message)

    def _run(self) -> None:
        attempt = 0
        first = True
        if self.record_path:
            self._rec = open(self.record_path, "a", buffering=1, encoding="utf-8")
        while not self._stop.is_set():
            opened_at = 0.0
            try:
                sws = self._make_client()

                def on_open(_ws=None):
                    nonlocal opened_at
                    opened_at = time.time()
                    self.connected, self.last_error = True, None
                    self.last_msg_at = time.time()
                    with self._lock:
                        self._subscribed = set()
                    log.info("feed: connected%s", "" if first else f" (reconnect #{self.reconnects})")
                    self._apply()
                    if not first and self.on_connect:
                        self.on_connect(True)

                def on_close(*_a):
                    if self.connected:
                        log.warning("feed: disconnected")
                    self.connected = False

                def on_error(*a):
                    self.last_error = "feed error: " + " ".join(str(x)[:80] for x in a)
                    log.warning("feed: %s", self.last_error)

                sws.on_open, sws.on_data, sws.on_error, sws.on_close = on_open, self._handle, on_error, on_close
                # the SDK's own close / error callbacks mis-handle current websocket-client signatures and try their own retry: use ours
                sws._on_close = lambda *a: on_close()
                sws._on_error = lambda *a: on_error(*a[1:])
                self._sws = sws
                sws.connect()                                  # blocks until the socket closes
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {str(e)[:100]}"
                log.warning("feed: stopped (%s)", self.last_error)
            self.connected = False
            if self._stop.is_set():
                break
            attempt = 0 if (opened_at and self.messages and time.time() - opened_at > 30) else attempt + 1
            wait = BACKOFF[min(attempt, len(BACKOFF)) - 1] if attempt else BACKOFF[0]
            self.reconnects += 1
            first = False
            log.info("feed: reconnecting in %ss", wait)
            if self._stop.wait(wait):
                break
        if self._rec:
            self._rec.close()

    def _watch(self) -> None:
        """No data for `stall_s` while a wanted exchange is open => the feed is dead: close the socket, the run loop reconnects."""
        while not self._stop.wait(self.watch_s):
            if not self.connected or not self._wanted:
                continue
            exchanges = {ex for ex, _ in self._wanted}
            if not any(calendar.is_open(ex) for ex in exchanges):
                continue
            if time.time() - self.last_msg_at > self.stall_s:
                log.warning("feed: no data for %.0fs during market hours, reconnecting", time.time() - self.last_msg_at)
                self.last_error = "stalled"
                self.last_msg_at = time.time()
                self._close_socket()
