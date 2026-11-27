"""Live ticks from Angel One's SmartWebSocketV2, kept in memory and read by the chart through /api/market/ticks.

One background thread holds ONE websocket for the whole app. Screens ask for the tokens they show (`ensure`); new tokens are subscribed on the
open socket and re-subscribed after every reconnect. Nothing here invents a price: a token with no tick yet is simply absent.
"""
import logging
import os
import threading
import time

from app.core.config import get_settings

log = logging.getLogger(__name__)

EXCHANGE_TYPE = {"NSE": 1, "NFO": 2, "BSE": 3, "BFO": 4, "MCX": 5}
MAX_TOKENS = 300
LTP_MODE = 1


def key_of(exchange: str, token: str) -> str:
    return f"{exchange}:{token}"


class LiveFeed:
    def __init__(self):
        self._lock = threading.Lock()
        self._wanted: set[tuple[str, str]] = set()
        self._ticks: dict[str, tuple[float, float, int | None]] = {}   # key -> (ltp, received_at, exchange_ts_ms)
        self._sws = None
        self._open = False
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._stop = threading.Event()

    # ---- public ----
    def status(self) -> dict:
        return {"connected": self._open, "subscribed": len(self._wanted), "error": self._last_error}

    def ensure(self, specs: list[tuple[str, str]]) -> None:
        """Make sure these (exchange, token) pairs are followed; start the feed thread on first use."""
        fresh = []
        with self._lock:
            for ex, tok in specs:
                if ex in EXCHANGE_TYPE and (ex, tok) not in self._wanted and len(self._wanted) < MAX_TOKENS:
                    self._wanted.add((ex, tok))
                    fresh.append((ex, tok))
        if os.environ.get("DISABLE_ENGINE") or not get_settings().angel_api_key:
            return
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="live-feed")
            self._thread.start()
        elif fresh and self._open:
            self._subscribe(fresh)

    def get(self, specs: list[tuple[str, str]]) -> dict[str, dict]:
        now = time.time()
        out = {}
        for ex, tok in specs:
            t = self._ticks.get(key_of(ex, tok))
            if t:
                out[key_of(ex, tok)] = {"ltp": t[0], "age": round(now - t[1], 1), "ts": t[2]}
        return out

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._sws:
                self._sws.close_connection()
        except Exception:  # noqa: BLE001
            pass

    # ---- internals ----
    def _on_tick(self, msg) -> None:
        try:
            ex = next((n for n, c in EXCHANGE_TYPE.items() if c == msg.get("exchange_type")), None)
            if ex is None or msg.get("last_traded_price") is None:
                return
            tok = str(msg["token"]).strip('"')
            div = 1e7 if msg.get("exchange_type") == 13 else 100.0   # prices arrive in paise
            self._ticks[key_of(ex, tok)] = (msg["last_traded_price"] / div, time.time(), msg.get("exchange_timestamp"))
        except Exception:  # noqa: BLE001
            log.exception("bad tick")

    def _subscribe(self, pairs: list[tuple[str, str]]) -> None:
        groups: dict[int, list[str]] = {}
        for ex, tok in pairs:
            groups.setdefault(EXCHANGE_TYPE[ex], []).append(tok)
        try:
            self._sws.subscribe("sahi" + str(int(time.time()))[-6:], LTP_MODE,
                                [{"exchangeType": t, "tokens": toks} for t, toks in groups.items()])
        except Exception as e:  # noqa: BLE001
            self._last_error = f"subscribe failed: {type(e).__name__}"
            log.warning("live feed %s", self._last_error)

    def _run(self) -> None:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2

        from app.market_data import angel

        while not self._stop.is_set():
            try:
                client = angel.provider.session()
                s = get_settings()
                sws = SmartWebSocketV2(client.access_token, s.angel_api_key, s.angel_client_code, client.getfeedToken(), max_retry_attempt=0)

                def on_open(_ws):
                    self._open, self._last_error = True, None
                    log.info("Angel live feed connected")
                    with self._lock:
                        pairs = list(self._wanted)
                    if pairs:
                        self._subscribe(pairs)

                def on_data(_ws, message):
                    self._on_tick(message)

                def on_error(*a):
                    self._last_error = "feed error: " + " ".join(str(x)[:80] for x in a)

                def on_close(_ws):
                    self._open = False

                sws.on_open, sws.on_data, sws.on_error, sws.on_close = on_open, on_data, on_error, on_close
                self._sws = sws
                sws.connect()          # blocks until the socket closes
            except Exception as e:  # noqa: BLE001
                self._last_error = f"{type(e).__name__}: {str(e)[:100]}"
                log.warning("live feed stopped: %s", self._last_error)
            self._open = False
            if self._stop.wait(5):
                return


feed = LiveFeed()
