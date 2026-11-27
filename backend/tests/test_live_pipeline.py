"""End-to-end tests of the live pipeline: replay, backfill, receiver reconnect, paper engine on ticks, restart idempotency."""
import asyncio
import datetime as dt
import threading
import time
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database.session import SessionLocal
from app.live import calendar, paper, repo, replay, runtime
from app.live.pipeline import Pipeline
from app.live.receiver import Receiver
from app.live.strategy import Binding, Signal, Strategy, front_month, place_signal
from app.live.tick import Tick
from app.models import Order, Position, Trade, TradingAccount
from app.models.live import LiveCandle, TradeLog
from app.models.market import Instrument
from app.trading import engine, pricing
from tests.conftest import register

IST, UTC = calendar.IST, calendar.UTC
D = Decimal
DAY = (2026, 11, 27)                    # a Friday


def ist(h, m, s=0, day=DAY):
    return dt.datetime(*day, h, m, s, tzinfo=IST)


def raw(ts, price, vol=0, token="2885", et=1):
    return {"subscription_mode": 2, "exchange_type": et, "token": f'"{token}"', "last_traded_price": int(round(price * 100)),
            "exchange_timestamp": int(ts.timestamp() * 1000), "volume_trade_for_the_day": vol}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from app.market_data import angel
    from app.market_data.provider import ProviderError

    def no_broker(*a, **k):
        raise ProviderError("no broker in tests")

    monkeypatch.setattr(angel.AngelProvider, "configured", staticmethod(lambda: False))   # a developer's real .env must never be used here
    monkeypatch.setattr(angel.provider, "get_ltp", no_broker)
    monkeypatch.setattr(angel.provider, "get_candles", no_broker)
    calendar.override({})
    pricing._cache.clear()
    runtime.store._ticks.clear(); runtime.store._at.clear()
    yield
    calendar.override(None)
    pricing._cache.clear()


@pytest.fixture()
def world(client):
    """A user with a paper account and RELIANCE (NSE) + a GOLD future (MCX) in the instrument table."""
    h = register(client)
    acc_id = client.post("/api/accounts", json={"name": "Main", "initial_capital": "1000000"}, headers=h).json()["id"]
    with SessionLocal() as db:
        rel = Instrument(exchange="NSE", symbol="RELIANCE", trading_symbol="RELIANCE-EQ", token="2885", instrument_type="EQ", lot_size=1)
        gold = Instrument(exchange="MCX", symbol="GOLD04DEC26FUT", trading_symbol="GOLD04DEC26FUT", token="495213", instrument_type="FUT",
                          underlying="GOLD", expiry=dt.date(2026, 12, 4), lot_size=100)
        db.add_all([rel, gold])
        db.commit()
        return {"acc": acc_id, "rel": rel.id, "gold": gold.id, "h": h}


def run(coro):
    return asyncio.run(coro)


def new_pipeline(**kw):
    return Pipeline(mode="replay", timers=False, **kw)


def candles(tf="1m", token="2885"):
    with SessionLocal() as db:
        rows = db.scalars(select(LiveCandle).where(LiveCandle.tf == tf, LiveCandle.token == token).order_by(LiveCandle.ts)).all()
    return [(r.ts.replace(tzinfo=UTC), r.open, r.high, r.low, r.close, r.volume, r.source) for r in rows]


# ======================================================================= replay vs broker candles
def make_session_ticks(start_min, minutes, token="2885"):
    """4 ticks per minute (o, h, l, c) with a rising cumulative volume, and the candles a broker would report for them."""
    ticks, expected, cum = [], [], 0
    for i in range(minutes):
        t0 = ist(9, start_min + i)
        o, h, l, c = 100 + i, 105 + i, 98 + i, 101 + i
        vols = []
        for j, (sec, px) in enumerate(((1, o), (20, h), (40, l), (58, c))):
            cum += 10
            vols.append(cum)
            ticks.append(raw(t0.replace(second=sec), px, cum, token))
        expected.append((t0.astimezone(UTC), o, h, l, c, 40 if i else 30))          # the very first tick has no earlier cumulative: 3 increments, then 4
    return ticks, expected


def test_replay_matches_broker_minute_candles(world):
    ticks, expected = make_session_ticks(15, 10)
    pl = new_pipeline()

    async def main():
        await pl.start()
        summary = await replay.play(pl, ticks)
        await pl.stop()
        return summary

    assert run(main())["ticks"] == 40
    got = candles("1m")
    assert [(g[0], g[1], g[2], g[3], g[4], g[5]) for g in got] == expected
    five = candles("5m")                                                             # 09:15-09:19 and 09:20-09:24, both complete
    assert [f[0] for f in five] == [ist(9, 15).astimezone(UTC), ist(9, 20).astimezone(UTC)]
    assert five[0][1:5] == (100, 109, 98, 105) and five[0][5] == 30 + 4 * 40
    assert pl.health()["dropped_ticks"]["duplicate"] == 0 and pl.errors == 0


def test_replay_is_repeatable_and_does_not_duplicate_candles(world):
    ticks, _ = make_session_ticks(15, 6)
    for _ in range(2):                                                               # same file twice = same rows, no duplicates
        pl = new_pipeline()

        async def main():
            await pl.start()
            await replay.play(pl, ticks)
            await pl.stop()
        run(main())
    assert len(candles("1m")) == 6


# ======================================================================= gap + backfill
def test_gap_is_backfilled_without_duplicates_or_holes(world):
    t1, _ = make_session_ticks(15, 5)                         # 09:15-09:19 live
    t2, _ = make_session_ticks(25, 3)                         # 09:25-09:27 live ... the feed was down 09:20-09:24
    for r in t2:
        r["volume_trade_for_the_day"] += 1000
    broker = []                                               # what the historical API holds: every minute 09:15..09:27, tz-suffixed
    for i in range(13):
        t = ist(9, 15 + i)
        broker.append([t.strftime("%Y-%m-%dT%H:%M:00+05:30"), 500 + i, 510 + i, 490 + i, 505 + i, 77])
    asked = []

    def fetcher(ex, tok, start, end):
        asked.append((start, end))
        return [r for r in broker if start <= dt.datetime.fromisoformat(r[0][:19]) < end]

    pl = new_pipeline(fetcher=fetcher)

    async def main():
        await pl.start()
        pl.clock.set(ist(9, 15).astimezone(UTC))
        await replay.play(pl, [r for r in t1] + [r for r in t2[:-1]])      # stop in the middle of minute 09:27
        pl.clock.set(ist(9, 27, 30).astimezone(UTC))
        n = await pl.backfill_token("NSE", "2885", now=ist(9, 27, 30).astimezone(UTC))
        n2 = await pl.backfill_token("NSE", "2885", now=ist(9, 27, 30).astimezone(UTC))     # a second backfill must add nothing
        await pl.drain()
        await pl.stop()
        return n, n2

    n, n2 = run(main())
    assert n == 5 and n2 == 0
    got = candles("1m")
    starts = [g[0] for g in got]
    assert starts == sorted(set(starts))                                             # no duplicate minute
    assert [ist(9, 15 + i).astimezone(UTC) for i in range(12)] == starts[:12]        # 09:15 .. 09:26, no hole
    assert {g[6] for g in got[:5]} == {"live"} and {g[6] for g in got[5:10]} == {"hist"}
    assert got[0][1] == 100 and got[5][1] == 505                                     # live candles kept as built; the gap minutes come from the broker
    five = {g[0]: g for g in candles("5m")}
    assert ist(9, 20).astimezone(UTC) in five and five[ist(9, 20).astimezone(UTC)][5] == 5 * 77   # built from the backfilled minutes
    assert asked[0][0] == dt.datetime(2026, 11, 27, 9, 20)                          # the broker was asked from the first MISSING minute only


def test_backfill_skips_when_nothing_is_missing(world):
    ticks, _ = make_session_ticks(15, 3)
    pl = new_pipeline(fetcher=lambda *a: pytest.fail("the broker must not be asked when no minute is missing"))

    async def main():
        await pl.start()
        await replay.play(pl, ticks)
        n = await pl.backfill_token("NSE", "2885", now=ist(9, 18, 30).astimezone(UTC))
        await pl.stop()
        return n

    assert run(main()) == 0


# ======================================================================= receiver: reconnect + heartbeat
class FakeSws:
    """The slice of SmartWebSocketV2 the receiver uses; `connect()` blocks until the socket is closed, like the real one."""
    instances: list = []

    def __init__(self):
        self.subscribed, self.unsubscribed, self.closed = [], [], threading.Event()
        self.on_open = self.on_data = self.on_error = self.on_close = None
        self.ready = threading.Event()
        FakeSws.instances.append(self)

    def subscribe(self, cid, mode, token_list):
        self.subscribed.append((mode, token_list))

    def unsubscribe(self, cid, mode, token_list):
        self.unsubscribed.append(token_list)

    def connect(self):
        self.on_open(None)
        self.ready.set()
        self.closed.wait()
        self._on_close()

    def close_connection(self):
        self.closed.set()


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_receiver_reconnects_and_resubscribes_everything(monkeypatch):
    import app.live.receiver as rcv
    monkeypatch.setattr(rcv, "BACKOFF", (0.01, 0.01))
    FakeSws.instances = []
    got, reconnected = [], []
    r = Receiver(got.append, reconnected.append, client_factory=FakeSws, stall_s=999)
    r.set_wanted({("NSE", "2885"), ("MCX", "495213")})
    r.start()
    assert wait_for(lambda: FakeSws.instances and FakeSws.instances[0].ready.is_set())
    s1 = FakeSws.instances[0]
    assert wait_for(lambda: s1.subscribed)
    modes = {m for m, _ in s1.subscribed}
    assert modes == {2}                                                              # QUOTE mode
    groups = {g["exchangeType"]: g["tokens"] for _, tl in s1.subscribed for g in tl}
    assert groups == {1: ["2885"], 5: ["495213"]}                                    # grouped by exchange: NSE_CM=1, MCX_FO=5
    s1.on_data(None, {"token": "1"})
    assert got == [{"token": "1"}] and r.status()["messages"] == 1
    s1.close_connection()                                                            # kill the socket mid-session
    assert wait_for(lambda: len(FakeSws.instances) == 2 and FakeSws.instances[1].ready.is_set())
    s2 = FakeSws.instances[1]
    assert wait_for(lambda: s2.subscribed and reconnected == [True])
    assert {g["exchangeType"]: g["tokens"] for _, tl in s2.subscribed for g in tl} == groups     # everything subscribed again
    assert r.reconnects >= 1 and r.connected
    r.set_wanted({("NSE", "2885")})                                                  # a token nobody needs any more is unsubscribed
    assert wait_for(lambda: s2.unsubscribed)
    r.stop()


def test_receiver_heartbeat_reconnects_only_when_the_market_is_open(monkeypatch):
    import app.live.receiver as rcv
    monkeypatch.setattr(rcv, "BACKOFF", (0.01,))
    FakeSws.instances = []
    open_now = {"v": False}
    monkeypatch.setattr(rcv.calendar, "is_open", lambda ex, now=None, grace_after_close_s=0.0: open_now["v"])
    r = Receiver(lambda m: None, client_factory=FakeSws, stall_s=0.2, watch_s=0.05)
    r.set_wanted({("NSE", "2885")})
    r.start()
    assert wait_for(lambda: FakeSws.instances and FakeSws.instances[0].ready.is_set())
    time.sleep(0.6)
    assert len(FakeSws.instances) == 1                                               # silence outside market hours is normal
    open_now["v"] = True
    assert wait_for(lambda: len(FakeSws.instances) >= 2)                             # silence DURING market hours = dead feed
    assert r.last_error == "stalled" or r.reconnects >= 1
    r.stop()


# ======================================================================= paper engine on ticks
def acct_obj(db, world):
    return db.get(TradingAccount, world["acc"])


def put_price(inst_token, ex, price):
    runtime.store.update(Tick(inst_token, "X", ex, price, 0, dt.datetime.now(IST), time.time()))


def test_limit_buy_fills_on_a_tick_at_or_below_the_limit(world):
    with SessionLocal() as db:
        o = engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="LIMIT", product="DELIVERY",
                               quantity=10, limit_price=D("100"), stop_loss=None, target=None, strategy_id=None, idempotency_key=None)
        assert o.status == "PENDING"
    assert paper.armed()[world["rel"]] == ("NSE", "2885")
    assert paper.on_tick(world["rel"], 100.5)[0] == []                               # above the limit: nothing
    ev, users = paper.on_tick(world["rel"], 99.5)
    assert ev and users
    with SessionLocal() as db:
        o = db.scalar(select(Order))
        assert o.status == "EXECUTED" and o.exec_price == D("99.50")                 # filled at the better (observed) price
        log = db.scalars(select(TradeLog)).all()
        assert [(l.event, l.reason) for l in log] == [("FILL", "ENTRY")]


def test_stop_loss_target_and_gap_through_the_stop(world):
    put_price("2885", "NSE", 100.0)
    with SessionLocal() as db:
        engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="MARKET", product="DELIVERY",
                           quantity=10, limit_price=None, stop_loss=D("98"), target=D("110"), strategy_id=None, idempotency_key=None)
    assert paper.on_tick(world["rel"], 98.5)[0] == []
    ev, _ = paper.on_tick(world["rel"], 95.0)                                        # the next session opens at 95: far below the 98 stop
    assert ev
    with SessionLocal() as db:
        t = db.scalar(select(Trade))
        assert t.exit_reason == "STOP_LOSS" and t.exit_price == D("95.00")           # filled at the first price seen, NOT at 98
        assert [(l.event, l.reason) for l in db.scalars(select(TradeLog).order_by(TradeLog.id))] == [("FILL", "ENTRY"), ("EXIT", "STOP_LOSS")]


def test_short_trigger_and_target_for_sell_positions(world):
    put_price("495213", "MCX", 1250.0)
    with SessionLocal() as db:
        engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["gold"]), side="SELL", order_type="MARKET", product="NRML",
                           quantity=100, limit_price=None, stop_loss=D("1255"), target=D("1240"), strategy_id=None, idempotency_key=None)
    assert paper.on_tick(world["gold"], 1254.0)[0] == []
    assert paper.on_tick(world["gold"], 1239.0)[0]
    with SessionLocal() as db:
        assert db.scalar(select(Trade)).exit_reason == "TARGET"


def test_intraday_square_off_at_session_end(world):
    put_price("2885", "NSE", 100.0)
    with SessionLocal() as db:
        engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="MARKET", product="INTRADAY",
                           quantity=10, limit_price=None, stop_loss=None, target=None, strategy_id=None, idempotency_key=None)
        p = db.scalar(select(Position))
        p.opened_at = ist(10, 0).astimezone(UTC)
        db.commit()
    px = lambda ex, tok: 101.0
    assert paper.square_off_intraday(ist(15, 29, 59).astimezone(UTC), px)[0] == []                    # one second before the close
    ev, users = paper.square_off_intraday(ist(15, 30, 0).astimezone(UTC), px)
    assert ev and users
    assert paper.square_off_intraday(ist(15, 31).astimezone(UTC), px)[0] == []                        # already closed: idempotent
    with SessionLocal() as db:
        assert db.scalar(select(Trade)).exit_reason == "EOD"
        assert db.scalar(select(func.count()).select_from(Trade)) == 1


def test_square_off_waits_for_a_price_and_catches_up_overnight(world):
    put_price("2885", "NSE", 100.0)
    with SessionLocal() as db:
        engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="MARKET", product="INTRADAY",
                           quantity=10, limit_price=None, stop_loss=None, target=None, strategy_id=None, idempotency_key=None)
        p = db.scalar(select(Position))
        p.opened_at = ist(10, 0).astimezone(UTC)
        db.commit()
    assert paper.square_off_intraday(ist(16, 0).astimezone(UTC), lambda e, t: None)[0] == []          # no price: left open
    ev, _ = paper.square_off_intraday(ist(9, 20, day=(2026, 11, 30)).astimezone(UTC), lambda e, t: 99.0)   # the app was down at the close: next Monday
    assert ev


def test_mcx_intraday_squares_off_at_its_own_close(world):
    put_price("495213", "MCX", 1250.0)
    with SessionLocal() as db:
        engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["gold"]), side="BUY", order_type="MARKET", product="INTRADAY",
                           quantity=100, limit_price=None, stop_loss=None, target=None, strategy_id=None, idempotency_key=None)
        p = db.scalar(select(Position))
        p.opened_at = ist(18, 0).astimezone(UTC)
        db.commit()
    assert paper.square_off_intraday(ist(15, 31).astimezone(UTC), lambda e, t: 1.0)[0] == []          # NSE is shut, MCX is not
    assert paper.square_off_intraday(ist(23, 29).astimezone(UTC), lambda e, t: 1.0)[0] == []
    assert paper.square_off_intraday(ist(23, 30).astimezone(UTC), lambda e, t: 1251.0)[0]


def test_restart_does_not_refill_or_reexit(world):
    """The same ticks replayed through a brand-new pipeline (a restart) change nothing that is already in the database."""
    with SessionLocal() as db:
        engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="LIMIT", product="DELIVERY",
                           quantity=10, limit_price=D("100"), stop_loss=D("97"), target=None, strategy_id=None, idempotency_key=None)
    ticks = [raw(ist(10, 0, 5), 99.0, 10), raw(ist(10, 0, 30), 96.5, 20), raw(ist(10, 1, 5), 96.0, 30)]

    def snapshot():
        with SessionLocal() as db:
            return (db.scalar(select(func.count()).select_from(Order)), db.scalar(select(func.count()).select_from(Position)),
                    db.scalar(select(func.count()).select_from(Trade)), db.scalar(select(func.count()).select_from(TradeLog)))

    async def once():
        pl = new_pipeline()
        await pl.start()
        pl._last["armed"] = -10.0
        await pl.advance(ist(10, 0, 1).astimezone(UTC))            # arm: the limit order is pending
        await replay.play(pl, ticks[:1])
        await pl.advance(ist(10, 0, 10).astimezone(UTC))           # the fill armed the stop; refresh the armed set
        await replay.play(pl, ticks[1:])
        await pl.stop()

    run(once())
    first = snapshot()
    assert first == (1, 1, 1, 2)                                                     # 1 order, 1 position (closed), 1 trade, FILL + EXIT
    run(once())
    assert snapshot() == first                                                       # restart: nothing re-filled, nothing re-exited
    with SessionLocal() as db:
        assert db.scalar(select(Position)).status == "CLOSED"
        assert db.scalar(select(Trade)).exit_price == D("96.50")


def test_slippage_setting_is_adverse(world, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "paper_slippage_pct", "1")
    put_price("2885", "NSE", 100.0)
    with SessionLocal() as db:
        o = engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="MARKET", product="DELIVERY",
                               quantity=1, limit_price=None, stop_loss=None, target=None, strategy_id=None, idempotency_key=None)
        assert o.exec_price == D("101.00")


def test_stale_price_is_refused_when_the_feed_is_down(world, monkeypatch):
    monkeypatch.setattr(runtime.store, "is_stale", lambda ex, tok: True)
    with SessionLocal() as db:
        with pytest.raises(pricing.PriceUnavailable, match="stale"):
            engine.place_order(db, acct_obj(db, world), db.get(Instrument, world["rel"]), side="BUY", order_type="MARKET", product="DELIVERY",
                               quantity=1, limit_price=None, stop_loss=None, target=None, strategy_id=None, idempotency_key=None)


def test_store_marks_stale_after_60s_only_while_open():
    clock = runtime.Clock() if hasattr(runtime, "Clock") else None
    from app.live.core import Clock, LatestPriceStore
    c = Clock()
    s = LatestPriceStore(c)
    c.set(ist(10, 0).astimezone(UTC))
    s.update(Tick("1", "X", "NSE", 1.0, 0, ist(10, 0), 0.0))
    assert s.state("NSE", "1") == "live"
    c.set(ist(10, 1, 1).astimezone(UTC))
    assert s.state("NSE", "1") == "stale" and s.is_stale("NSE", "1")
    c.set(ist(16, 0).astimezone(UTC))
    assert s.state("NSE", "1") == "closed"                                           # silence after the close is normal
    assert s.state("NSE", "999") == "unknown"


# ======================================================================= strategy
class Always(Strategy):
    name = "always"

    def __init__(self):
        self.seen = []

    def on_candle(self, symbol, tf, candle, history):
        self.seen.append((symbol, tf, candle.close, len(history)))
        return Signal("BUY", candle.close, candle.close - 2, candle.close + 5, "test")


def test_signal_becomes_one_paper_order_even_if_the_candle_is_replayed(world):
    put_price("2885", "NSE", 100.0)
    st = Always()
    b = Binding(st, world["acc"], "NSE", tf="1m", symbol="RELIANCE", lots=3, product="DELIVERY")
    ticks, _ = make_session_ticks(15, 3)
    pl = new_pipeline()
    pl.runner.add(b)

    async def main():
        await pl.start()
        b.resolve(ist(9, 15).astimezone(UTC))
        await replay.play(pl, ticks)
        await pl.stop()
    run(main())
    assert [s[:2] for s in st.seen] == [("RELIANCE", "1m")] * 3
    assert st.seen[2][3] == 3                                                        # history grows with each closed candle
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 3
        o = db.scalars(select(Order).order_by(Order.id)).all()[0]
        assert o.idempotency_key.startswith("sig-always") and o.quantity == 3 and o.stop_loss is not None
        sig_log = db.scalars(select(TradeLog).where(TradeLog.event == "FILL")).all()
        assert {l.reason for l in sig_log} == {"SIGNAL"}
    # the same candle again (restart / backfill overlap): same idempotency key -> the existing order, not a new one
    from app.live.candles import Candle
    c = Candle("2885", "RELIANCE", "NSE", "1m", ist(9, 15).astimezone(UTC), 100, 101, 99, 100)
    place_signal(b, Signal("BUY", 100, 98, 105), c)
    place_signal(b, Signal("BUY", 100, 98, 105), c)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Order).where(Order.idempotency_key.like("sig-always%"))) == 3        # unchanged: the same candle gives the same key


def test_futures_rollover_follows_the_next_month(world):
    with SessionLocal() as db:
        db.add(Instrument(exchange="MCX", symbol="GOLD05JAN27FUT", trading_symbol="GOLD05JAN27FUT", token="777", instrument_type="FUT",
                          underlying="GOLD", expiry=dt.date(2027, 1, 5), lot_size=100))
        db.commit()
    b = Binding(Always(), world["acc"], "MCX", tf="5m", underlying="GOLD")
    assert b.resolve(ist(12, 0, day=(2026, 11, 27)).astimezone(UTC))[2] == "GOLD04DEC26FUT"
    assert b.resolve(ist(12, 0, day=(2026, 12, 4)).astimezone(UTC))[2] == "GOLD04DEC26FUT"           # expiry day, session still running
    assert b.resolve(ist(23, 31, day=(2026, 12, 4)).astimezone(UTC))[2] == "GOLD05JAN27FUT"          # after its last session: next month
    assert b.resolve(ist(10, 0, day=(2026, 12, 7)).astimezone(UTC))[1] == "777"


# ======================================================================= websocket push + health
def test_websocket_requires_a_valid_token_and_pushes_first_paint(client, world):
    h = world["h"]
    token = h["Authorization"].split()[1]
    runtime.store.update(Tick("2885", "RELIANCE", "NSE", 1394.5, 0, dt.datetime.now(IST), time.time()))
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/ticks?token=bad"):
            pass
    with client.websocket_connect(f"/ws/ticks?token={token}") as ws:
        assert ws.receive_json()["type"] == "feed"
        ws.send_json({"op": "subscribe", "symbols": ["NSE:2885", "BAD", "XXX:1"]})
        m = ws.receive_json()
        assert m["type"] == "tick" and m["k"] == "NSE:2885" and m["ltp"] == 1394.5
    assert client.get("/api/live/health").json()["mode"] == "off"


def test_pipeline_health_and_ui_drops_oldest_only():
    pl = new_pipeline()
    for i in range(2500):
        pl.bus.publish("tick", Tick("1", "X", "NSE", float(i + 1), 0, ist(10, 0), 0.0))
    s = pl.bus.sizes()["tick"]
    assert s[0] == 2500 and s[1] == 2500 and s[2] == 2000                            # the candle and order queues keep everything; the UI queue drops
    assert pl.bus.dropped_ui == 500
    h = pl.health()
    assert h["mode"] == "replay" and h["feed"]["state"] == "replay" and h["error_count"] == 0 and "queues" in h
