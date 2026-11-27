# Live market-data pipeline

Paper trading only: no real order is ever sent. Broker = Angel One SmartAPI. Code: `backend/app/live/`.

## How a tick flows

```
Angel WebSocket (SmartWebSocketV2, QUOTE mode)
   |  thread "tick-receiver": subscribe, heartbeat, reconnect. Hands raw messages over with loop.call_soon_threadsafe
   v
raw_q (asyncio.Queue)
   v
Normalizer      paise -> rupees, exchange timestamp -> IST, drops ltp<=0 / duplicates / ticks outside the session
   v
LatestPriceStore (token -> last Tick; STALE if quiet > 60 s while the exchange is open)
   v
Bus "tick" ---> candle task  (unbounded) --> closed 1m candles --> Aggregator --> 5m / 15m / 1d  --> Bus "candle"
          |                                                                                          |-> writer task (DB table live_candles)
          |                                                                                          |-> strategy task (Signal -> paper MARKET order)
          |---> orders task  (unbounded) --> paper engine: limit, stop (TRIGGER), stop-loss, target; fills/exits -> trade_log
          '---> ui queue     (bounded 2000, drops the OLDEST) --> /ws/ticks (<= 4 updates/s/symbol) + fills + feed status
timer task (1 Hz): flush quiet minutes (M+1:00 + 2 s), sweep buckets, EOD square-off, subscription sync, feed status, 08:30 master, 08:50 login
```

Only the UI queue ever drops anything. Candle, order and DB queues are unbounded: a backlog shows in `/health` instead of losing data.

## Files

| File | Stage |
|---|---|
| `receiver.py` | websocket thread: QUOTE mode grouped by exchange (NSE_CM=1, NSE_FO=2, MCX_FO=5), token limit (`FEED_MAX_TOKENS`, default 500), stall watchdog, backoff 1 2 4 ... 30 s, resubscribe, optional recorder |
| `tick.py` | `Tick` dataclass + `Normalizer` |
| `calendar.py` | sessions: NSE 09:15-15:30, MCX 09:00-23:30 (23:55 while US DST), holidays / special / late open from the `market_calendar` table |
| `core.py` | `Clock` (real or virtual), `LatestPriceStore`, `Bus` |
| `candles.py` | `CandleBuilder` (ticks to 1m), `Aggregator` (1m to 5m/15m/1d, anchored at the session open), `History` |
| `repo.py` | `live_candles` table, backfill of missing minutes from `getCandleData` |
| `paper.py` | when to call the paper engine: armed instruments, tick processing, intraday square-off |
| `strategy.py` | `Strategy`, `Signal`, `Binding` (front-month futures rollover), `StrategyRunner` |
| `pipeline.py` | wires everything, health, daily jobs |
| `ws.py` | browser websocket `/ws/ticks` |
| `replay.py`, `scripts/replay.py` | tick replay |
| `runtime.py` | process-wide `store` / `pipeline` handles |

The paper engine itself is `app/trading/engine.py` (orders, ledger, positions, charges). It is idempotent: an order flips PENDING -> EXECUTING in one atomic UPDATE and a position closes once, so a restart or a repeated tick cannot fill or exit twice. Every fill and exit is also written to `trade_log` (reason: ENTRY, SIGNAL, STOP_LOSS, TARGET, MANUAL, EOD, EXPIRY).

## Rules worth knowing

* **Candles** close on the first tick of a later minute, or by timer at M+1:00 + 2 s. 5m/15m/1d are built from closed 1m candles only. A minute is keyed by (token, time), so a backfilled minute that already exists is never added twice. Live candles win over backfilled ones.
* **Volume**: the feed carries cumulative day volume; a candle's volume is the increase during its minute. The very first tick we see for a token has no earlier cumulative, so its own volume is not counted.
* **Backfill** runs at startup and after every reconnect, for the subscribed tokens (at most 30 per pass). It asks the broker only from the first missing minute, and never for the minute still in progress.
* **Gap through a stop**: the engine fills at the first price it sees, not at the stop level. `PAPER_SLIPPAGE_PCT` (default 0) adds adverse slippage to market fills, stop entries and stop-loss exits.
* **Stale prices**: a symbol is STALE after 60 s of silence while its exchange is open. A market order is refused when the stored price is stale AND the feed is down. If the feed is up but the symbol is just quiet, the REST price is used.
* **Intraday square-off** at the session end of that exchange (reason `EOD`); `INTRADAY_SQUAREOFF_MINUTES_BEFORE_CLOSE` moves it earlier. A position left over from an earlier day (app was down) is squared off at the last known price at the next pass.
* **Rollover**: a `Binding(underlying="BANKNIFTY", exchange="NFO")` always follows the nearest future that has not expired (on its expiry day until the last session ends). The instrument master is refreshed at 08:30 IST and the broker login at 08:50 IST. A 403 from a REST call is a rate limit: it backs off and retries, it does not log in again.

## Strategies

```python
from app.live.strategy import Strategy, Signal, Binding

class Breakout(Strategy):
    name = "breakout"
    def on_candle(self, symbol, tf, candle, history):
        if len(history) > 20 and candle.close > max(c.high for c in history[-21:-1]):
            return Signal("BUY", candle.close, stop=candle.low, target=candle.close * 1.01, reason="20-bar high")

pipeline.runner.add(Binding(Breakout(), account_id=1, exchange="NFO", underlying="BANKNIFTY", tf="5m", lots=1))
```

A strategy only sees closed candles and never talks to the broker. The order key is `sig-<strategy>-<instrument>-<tf>-<candle time>`, so the same candle can never place two orders.

## Run it

Live (default): put the Angel keys in `backend/.env` and start the app. `GET /health` (or `/api/live/health`) shows the feed.

Replay, no market needed:

```
cd backend
.venv\Scripts\python scripts\replay.py --make-sample sample.jsonl
.venv\Scripts\python scripts\replay.py sample.jsonl             # prints the candles it built
# or watch it in the browser:
set FEED_MODE=replay & set REPLAY_FILE=sample.jsonl & set REPLAY_SPEED=1 & .venv\Scripts\uvicorn app.main:app
```

Record real ticks to replay later: set `RECORD_TICKS=/path/ticks.jsonl` on the server (one raw message per line).

Calendar edits (no deploy): `scripts\calendar_admin.py holiday 2026-12-25 NSE "Christmas"`, `special`, `late_open`, `sync-nse`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PASSWORD` (PIN), `ANGEL_TOTP_SECRET` | - | broker login (never logged) |
| `FEED_MODE` | `live` | `live`, `replay`, or `off` |
| `REPLAY_FILE`, `REPLAY_SPEED` | - / `1` | tick file and speed for `FEED_MODE=replay` (0 = fastest) |
| `RECORD_TICKS` | - | append every raw tick to this JSONL file |
| `FEED_STALL_SECONDS` | `20` | silence during market hours that triggers a reconnect |
| `FEED_MAX_TOKENS` | `500` | tokens on the one connection |
| `PAPER_SLIPPAGE_PCT` | `0` | adverse slippage in % |
| `INTRADAY_SQUAREOFF_MINUTES_BEFORE_CLOSE` | `0` | square-off lead time |

## Tests

`python -m pytest tests/test_live_candles.py tests/test_live_pipeline.py -q` covers: paise / IST / drop rules, minute-boundary ticks (hh:mm:59.999 vs hh:mm+1:00.000), the 2 s timer close, 5m/15m/1d from 1m, replay candles vs the candles a broker would report, backfill without duplicates or holes, receiver reconnect + resubscribe + heartbeat (only in market hours), limit / stop / target / gap-through-stop, EOD square-off (NSE and MCX), restart idempotency, stale handling, slippage, strategy signals, rollover, MCX DST close, holiday / late open / special sessions, and the websocket.
