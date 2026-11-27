import datetime as dt

import pytest

from app.live import calendar
from app.live.candles import Aggregator, Candle, CandleBuilder
from app.live.tick import Normalizer, Tick

IST, UTC = calendar.IST, calendar.UTC


@pytest.fixture(autouse=True)
def _no_calendar_exceptions():
    calendar.override({})
    yield
    calendar.override(None)


def ist(h, m, s=0, ms=0, day=(2026, 11, 27)):
    return dt.datetime(*day, h, m, s, ms * 1000, tzinfo=IST)


def tick(ts, ltp, vol=0, token="2885", ex="NSE"):
    return Tick(token, "RELIANCE", ex, ltp, vol, ts, 0.0)


def raw(ts, price, vol=0, token="2885", et=1):
    return {"exchange_type": et, "token": f'"{token}"', "last_traded_price": int(round(price * 100)),
            "exchange_timestamp": int(ts.timestamp() * 1000), "volume_trade_for_the_day": vol}


# ---------------- normalizer ----------------
def test_normalizer_paise_ist_and_drops():
    n = Normalizer(lambda ex, tok: "RELIANCE" if tok == "2885" else None)
    t = n(raw(ist(10, 0, 5), 1394.5, 100), 1.0)
    assert t.ltp == 1394.5 and t.symbol == "RELIANCE" and t.exchange == "NSE"
    assert t.exchange_ts.utcoffset() == dt.timedelta(hours=5, minutes=30) and t.exchange_ts.hour == 10
    assert n(raw(ist(10, 0, 5), 1394.5, 100), 2.0) is None                       # duplicate
    assert n(raw(ist(10, 0, 6), 0), 3.0) is None                                 # ltp <= 0
    assert n(raw(ist(9, 10), 1390), 4.0) is None                                 # pre-open: outside the session
    assert n(raw(ist(15, 31), 1390), 5.0) is None                                # beyond the 30 s grace
    assert n(raw(ist(15, 30, 10), 1390), 6.0) is not None                        # the last prints of the close
    assert n(raw(ist(10, 1), 5, token="999"), 7.0) is None                       # unknown token
    assert n({"token": "1"}, 8.0) is None
    assert n.dropped == {"bad": 1, "price": 1, "duplicate": 1, "session": 2, "unknown": 1}


def test_normalizer_mcx_evening_session():
    n = Normalizer(lambda ex, tok: "GOLD")
    assert n(raw(ist(21, 0), 125000, et=5, token="1"), 1.0) is not None           # NSE would be closed
    assert n(raw(ist(23, 40), 125000, et=5, token="2"), 1.0) is not None if calendar.mcx_close(dt.date(2026, 11, 27)) == dt.time(23, 55) else True


# ---------------- 1-minute candles ----------------
def test_boundary_59_999_vs_next_minute():
    b = CandleBuilder()
    assert b.on_tick(tick(ist(10, 0, 5), 100, 10)) == []
    assert b.on_tick(tick(ist(10, 0, 59, 999), 101, 15)) == []                    # still minute 10:00
    closed = b.on_tick(tick(ist(10, 1, 0, 0), 102, 18))                           # 10:01:00.000 -> a new minute
    assert len(closed) == 1
    c = closed[0]
    assert (c.start, c.open, c.high, c.low, c.close) == (ist(10, 0).astimezone(UTC), 100, 101, 100, 101)
    assert c.volume == 5                                                         # 15 - 10 (the first tick has no earlier cumulative)
    assert b.open_candles()[0].open == 102 and b.open_candles()[0].volume == 3


def test_flush_timer_closes_quiet_symbol_after_2s():
    b = CandleBuilder()
    b.on_tick(tick(ist(10, 0, 30), 100))
    assert b.flush(ist(10, 1, 1).astimezone(UTC)) == []                           # M+1:00 + 1 s: too early
    out = b.flush(ist(10, 1, 2).astimezone(UTC))
    assert len(out) == 1 and out[0].close == 100
    assert b.flush(ist(10, 5).astimezone(UTC)) == []                              # closed once only


def test_late_tick_never_rewrites_a_closed_minute():
    b = CandleBuilder()
    b.on_tick(tick(ist(10, 1, 5), 100))
    b.on_tick(tick(ist(10, 0, 59), 90))                                           # older minute than the open candle
    assert b.late_ticks == 1 and b.open_candles()[0].low == 100


# ---------------- higher timeframes ----------------
def minute(start_ist, o, h, l, c, v=1, token="2885"):
    return Candle(token, "RELIANCE", "NSE", "1m", start_ist.astimezone(UTC), o, h, l, c, v)


def test_5m_built_from_1m_anchored_at_session_open():
    a = Aggregator(("5m",))
    for i in range(5):                                                           # 09:15 .. 09:19
        a.add_minute(minute(ist(9, 15 + i), 100 + i, 110 + i, 90 + i, 101 + i, 10))
    assert a.sweep(ist(9, 20, 1).astimezone(UTC)) == []                           # 09:20:01 -> not yet (needs +2 s or a later minute)
    out = a.sweep(ist(9, 20, 2).astimezone(UTC))
    assert len(out) == 1
    c = out[0]
    assert c.tf == "5m" and c.start == ist(9, 15).astimezone(UTC)
    assert (c.open, c.high, c.low, c.close, c.volume) == (100, 114, 90, 105, 50)
    assert a.sweep(ist(9, 40).astimezone(UTC)) == []                              # not emitted twice


def test_next_bucket_minute_closes_previous_bucket_immediately():
    a = Aggregator(("5m",))
    for i in range(5):
        a.add_minute(minute(ist(9, 15 + i), 1, 2, 0, 1))
    a.add_minute(minute(ist(9, 20), 1, 1, 1, 1))
    out = a.sweep(ist(9, 20, 1).astimezone(UTC))
    assert [c.start for c in out] == [ist(9, 15).astimezone(UTC)]


def test_duplicate_minute_is_ignored_and_daily_clips_to_session():
    a = Aggregator(("1d",))
    assert a.add_minute(minute(ist(9, 15), 1, 5, 1, 4, 3))
    assert not a.add_minute(minute(ist(9, 15), 9, 9, 9, 9, 99))                   # an overlapping backfill is not counted twice
    a.add_minute(minute(ist(15, 29), 4, 6, 3, 5, 7))
    assert a.sweep(ist(15, 29, 30).astimezone(UTC)) == []
    d = a.sweep(ist(15, 30, 2).astimezone(UTC))
    assert len(d) == 1 and d[0].start == ist(9, 15).astimezone(UTC)
    assert (d[0].open, d[0].high, d[0].low, d[0].close, d[0].volume) == (1, 6, 1, 5, 10)


def test_mcx_buckets_anchor_at_0900():
    a = Aggregator(("15m",))
    t0 = ist(9, 0)
    a.add_minute(Candle("5", "GOLD", "MCX", "1m", t0.astimezone(UTC), 1, 1, 1, 1))
    assert a.bucket("MCX", t0.astimezone(UTC), "15m")[0] == t0.astimezone(UTC)
    assert a.bucket("NSE", ist(9, 16).astimezone(UTC), "15m")[0] == ist(9, 15).astimezone(UTC)


# ---------------- calendar ----------------
def test_calendar_weekend_holiday_late_open_special():
    fri, sat = dt.date(2026, 11, 27), dt.date(2026, 11, 28)
    assert calendar.session("NSE", fri) == (dt.time(9, 15), dt.time(15, 30))
    assert calendar.session("NFO", sat) is None
    calendar.override({("2026-11-27", "NSE"): {"kind": "holiday", "start": None, "end": None, "note": ""},
                       ("2026-11-27", "MCX"): {"kind": "late_open", "start": "17:00", "end": None, "note": ""},
                       ("2026-11-28", "NSE"): {"kind": "special", "start": "18:15", "end": "19:15", "note": "Muhurat"}})
    assert calendar.session("NSE", fri) is None and calendar.session("NFO", fri) is None
    assert calendar.session("MCX", fri)[0] == dt.time(17, 0)
    assert not calendar.is_open("MCX", ist(12, 0))                                # morning closed
    assert calendar.is_open("MCX", ist(18, 0))
    assert calendar.session("NSE", sat) == (dt.time(18, 15), dt.time(19, 15))     # a special session on a Saturday
    assert calendar.is_open("NSE", ist(18, 30, day=(2026, 11, 28)))


def test_mcx_close_follows_us_dst():
    assert calendar.mcx_close(dt.date(2026, 7, 15)) == dt.time(23, 55)            # US daylight saving time
    assert calendar.mcx_close(dt.date(2026, 12, 15)) == dt.time(23, 30)
    assert calendar.mcx_close(dt.date(2026, 3, 5)) == dt.time(23, 30)             # US clocks move forward on 8 March 2026
    assert calendar.mcx_close(dt.date(2026, 3, 10)) == dt.time(23, 55)
    assert calendar.mcx_close(dt.date(2026, 10, 30)) == dt.time(23, 55)           # still daylight saving time ...
    assert calendar.mcx_close(dt.date(2026, 11, 2)) == dt.time(23, 30)            # ... until the clocks go back on 1 November 2026


def test_next_close_rolls_over_weekend():
    nxt = calendar.next_close("NSE", ist(16, 0))                                  # Friday after the close
    assert nxt.astimezone(IST).date() == dt.date(2026, 11, 30) and nxt.astimezone(IST).time() == dt.time(15, 30)


def test_json_log_line_has_stage_token_symbol():
    import json
    import logging

    from app.live.logs import JsonFormatter
    rec = logging.LogRecord("live", logging.INFO, "x.py", 1, "candle %s", ("closed",), None)
    rec.token, rec.symbol, rec.stage = "2885", "RELIANCE", "candles"
    d = json.loads(JsonFormatter().format(rec))
    assert d["msg"] == "candle closed" and d["token"] == "2885" and d["symbol"] == "RELIANCE" and d["stage"] == "candles" and d["level"] == "INFO"
