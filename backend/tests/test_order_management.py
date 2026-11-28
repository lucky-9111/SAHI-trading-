"""Order management: market status, after-market handling, execution rules, lifecycle, notifications, reliability.

All prices are mocked; no broker is contacted (pricing.execution_quote / pricing.depth / pricing._full_quote are patched). The engine clock
is pinned by the autouse `market_clock` fixture (Friday 27 Nov 2026 09:30 IST) and moved per test.
"""
import datetime as dt
import threading
import time
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.database.session import SessionLocal, engine as db_engine
from app.live import calendar, runtime
from app.live.tick import Tick
from app.models import LedgerEntry, Notification, Order, Position
from app.models.live import TradeLog
from app.models.market import Instrument
from app.trading import engine, market_status as ms, poller, pricing
from tests.test_trading import acct, balance, order, positions, px  # noqa: F401  (fixtures + helpers)

D = Decimal
IST = calendar.IST


def ist(y, mo, d, h, mi, s=0):
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=IST)


FRI_OPEN = ist(2026, 11, 27, 9, 30)
FRI_POST = ist(2026, 11, 27, 15, 45)
FRI_EVENING = ist(2026, 11, 27, 18, 0)
SAT = ist(2026, 11, 28, 11, 0)
MON_PRE = ist(2026, 11, 30, 9, 5)
MON_OPEN = ist(2026, 11, 30, 9, 15, 10)
MON_CLOSE = ist(2026, 11, 30, 15, 30)


def iid(symbol="RELIANCE"):
    with SessionLocal() as db:
        return db.scalar(select(Instrument.id).where(Instrument.symbol == symbol, Instrument.exchange == "NSE"))


def tick(price, at, symbol="RELIANCE", quote=None):
    """One fresh in-session price at time `at` (the clock moves there too)."""
    ms.set_clock(at)
    with SessionLocal() as db:
        return engine.process_price(db, iid(symbol), D(str(price)), at=at, quote=quote)


def get_order(client, auth, acct, oid):  # noqa: F811
    return client.get(f"/api/accounts/{acct}/orders/{oid}", headers=auth).json()


def kinds(oid):
    with SessionLocal() as db:
        return [n.kind for n in db.scalars(select(Notification).where(Notification.order_id == oid).order_by(Notification.id))]


@pytest.fixture()
def depth(monkeypatch):
    """Controllable 5-level book: {"bids": [(price, qty)], "asks": [...]}; empty = no depth available."""
    book = {"bids": [], "asks": []}

    def fake(inst, session_start):
        return tuple((D(str(p)), q) for p, q in book["bids"]), tuple((D(str(p)), q) for p, q in book["asks"])

    monkeypatch.setattr(pricing, "depth", fake)
    return book


# ============================================================================== 1. market open / closed, 2. weekends and holidays
def test_market_status_states():
    assert ms.status("NSE", FRI_OPEN).state == "OPEN" and ms.status("NSE", FRI_OPEN).is_open
    assert ms.status("NSE", ist(2026, 11, 27, 9, 15)).is_open and ms.status("NSE", ist(2026, 11, 27, 15, 30)).is_open   # edges inclusive
    assert ms.status("NSE", ist(2026, 11, 27, 9, 14, 59)).state == "PRE_OPEN"
    assert ms.status("NSE", ist(2026, 11, 27, 8, 59)).state == "CLOSED"
    assert ms.status("NSE", ist(2026, 11, 27, 15, 35)).state == "CLOSED"
    assert ms.status("NSE", FRI_POST).state == "POST_CLOSE"
    assert ms.status("NFO", ist(2026, 11, 27, 9, 5)).state == "CLOSED"                      # no pre-open in F&O
    assert ms.status("NSE", FRI_EVENING).state == "CLOSED" and not ms.status("NSE", FRI_EVENING).is_open
    assert ms.status("MCX", FRI_EVENING).is_open                                             # commodities trade till 23:30
    s = ms.status("NSE", SAT)
    assert s.state == "WEEKEND" and not s.is_open
    assert s.next_open == ist(2026, 11, 30, 9, 15).astimezone(dt.timezone.utc)               # Saturday -> Monday 09:15
    assert ms.status("NSE", FRI_OPEN).next_open is None


def test_holidays_and_special_sessions():
    calendar.override({("2026-12-25", "NSE"): {"kind": "holiday", "start": None, "end": None, "note": "Christmas"},
                       ("2026-11-29", "NSE"): {"kind": "special", "start": "18:00", "end": "19:00", "note": "Muhurat trading"}})
    xmas = ms.status("NSE", ist(2026, 12, 25, 10, 0))
    assert xmas.state == "HOLIDAY" and not xmas.is_open and "Christmas" in xmas.label
    assert ms.status("NSE", ist(2026, 12, 24, 16, 0)).next_open == ist(2026, 12, 28, 9, 15).astimezone(dt.timezone.utc)
    muhurat = ms.status("NSE", ist(2026, 11, 29, 18, 30))                                    # a Sunday special session
    assert muhurat.is_open and muhurat.special and "Muhurat" in muhurat.label
    assert not ms.status("NSE", ist(2026, 11, 29, 19, 5)).is_open
    assert ms.status("NSE", SAT).next_open == ist(2026, 11, 29, 18, 0).astimezone(dt.timezone.utc)


def test_holiday_blocks_execution_even_with_a_price(client, auth, acct, px):  # noqa: F811
    calendar.override({("2026-11-27", "NSE"): {"kind": "holiday", "start": None, "end": None, "note": "Test holiday"}})
    r = order(client, auth, acct).json()
    assert r["status"] == "PENDING" and r["after_market"] is True
    assert tick(1000, FRI_OPEN) == [] and positions(client, auth, acct) == []


def test_sessions_endpoint(client, auth):
    r = client.get("/api/market/sessions", headers=auth).json()
    by = {x["exchange"]: x for x in r["exchanges"]}
    assert by["NSE"]["state"] == "OPEN" and by["NSE"]["is_open"] and by["MCX"]["is_open"]
    assert r["server_time"].startswith("2026-11-27T04:00")                                  # 09:30 IST, from the backend clock


# ============================================================================== 3. market order during market hours
def test_market_order_during_hours_executes_with_notification(client, auth, acct, px):  # noqa: F811
    r = order(client, auth, acct, quantity=10).json()
    assert r["status"] == "FILLED" and r["filled_quantity"] == 10 and r["remaining_quantity"] == 0
    assert r["avg_price"] == "1000.00" and r["after_market"] is False and r["executed_at"]
    assert kinds(r["id"]) == ["ORDER_FILLED"]
    n = client.get("/api/notifications", headers=auth).json()
    assert n["items"][-1]["title"] == "Order executed successfully" and "10 @ ₹1,000.00" in n["items"][-1]["body"]


def test_market_order_fills_at_the_ask_plus_slippage(client, auth, acct, px, depth):  # noqa: F811
    client.put(f"/api/accounts/{acct}/order-settings", json={"after_hours_mode": "QUEUE", "slippage_pct": "0.1"}, headers=auth)
    depth["bids"], depth["asks"] = [(999.5, 500)], [(1000.5, 500)]
    buy = order(client, auth, acct, quantity=10).json()
    assert buy["avg_price"] == "1001.50"                                                      # ask 1000.50 + 0.1 %
    sell = order(client, auth, acct, symbol="TCS", side="SELL", quantity=10).json()
    assert sell["avg_price"] == "998.50"                                                      # bid 999.50 - 0.1 %


# ============================================================================== 4. market order after market hours
def test_market_order_after_hours_is_queued_never_filled_on_the_stale_price(client, auth, acct, px, market_clock):  # noqa: F811
    market_clock(FRI_EVENING)
    r = order(client, auth, acct, quantity=10).json()
    assert r["status"] == "PENDING" and r["after_market"] is True and r["exec_price"] is None and r["filled_quantity"] == 0
    assert r["expires_at"].startswith("2026-11-30T10:00")                                    # DAY = Monday's close (15:30 IST)
    assert positions(client, auth, acct) == [] and balance(client, auth, acct) == D("1000000")
    assert client.get(f"/api/accounts/{acct}/trades", headers=auth).json() == []
    assert kinds(r["id"]) == ["ORDER_PENDING_CLOSED"]
    with SessionLocal() as db:                                                               # a closed market ignores prices
        assert engine.process_price(db, iid(), D("1000")) == []


def test_reject_mode_rejects_orders_while_closed(client, auth, acct, px, market_clock):  # noqa: F811
    client.put(f"/api/accounts/{acct}/order-settings", json={"after_hours_mode": "REJECT"}, headers=auth)
    market_clock(SAT)
    pv = client.post(f"/api/accounts/{acct}/orders/preview", json={"symbol": "RELIANCE", "side": "BUY", "quantity": 1}, headers=auth).json()
    assert pv["market"]["state"] == "WEEKEND" and any("rejected" in e for e in pv["errors"])
    r = order(client, auth, acct, quantity=10).json()
    assert r["status"] == "REJECTED" and "market is closed" in r["reject_reason"]
    assert kinds(r["id"]) == ["ORDER_REJECTED"] and positions(client, auth, acct) == []
    gtt = order(client, auth, acct, order_type="LIMIT", limit_price="900", product="DELIVERY", validity="GTT").json()
    assert gtt["status"] == "PENDING"                                                         # GTT orders are still accepted


# ============================================================================== 5. queued order executes at the next session
def test_queued_order_executes_at_the_first_fresh_price_of_the_next_session(client, auth, acct, px, market_clock):  # noqa: F811
    market_clock(FRI_EVENING)
    oid = order(client, auth, acct, quantity=10).json()["id"]
    assert tick(1000, SAT) == []                                                              # weekend
    assert tick(1000, MON_PRE) == []                                                          # pre-open: still waiting
    stale = pricing.ExecQuote(D("1000"), ist(2026, 11, 27, 15, 29).astimezone(dt.timezone.utc), "test")
    assert tick(1000, MON_OPEN, quote=stale) == []                                            # Friday's last price, seen on Monday: no
    assert tick(1012, MON_OPEN) == [f"order {oid} FILLED"]                                    # first fresh Monday price
    o = get_order(client, auth, acct, oid)
    assert o["status"] == "FILLED" and o["avg_price"] == "1012.00"
    assert positions(client, auth, acct)[0]["avg_price"] == "1012.00"
    assert [h["kind"] for h in o["history"]] == ["ORDER_RECEIVED", "ORDER_PENDING_CLOSED", "ORDER_FILLED"]
    assert tick(1013, ist(2026, 11, 30, 9, 16)) == []                                         # never twice


def test_queued_limit_order_becomes_open_at_the_open(client, auth, acct, px, market_clock):  # noqa: F811
    market_clock(FRI_EVENING)
    oid = order(client, auth, acct, order_type="LIMIT", limit_price="990", quantity=5).json()["id"]
    assert tick(1000, MON_OPEN) == [f"order {oid} OPEN"]                                      # activated, not marketable
    assert get_order(client, auth, acct, oid)["status"] == "OPEN"
    assert tick(989, ist(2026, 11, 30, 9, 40)) == [f"order {oid} FILLED"]
    assert get_order(client, auth, acct, oid)["avg_price"] == "989.00"


# ============================================================================== 6. limit order price conditions
def test_limit_order_price_conditions(client, auth, acct, px, depth):  # noqa: F811
    buy = order(client, auth, acct, order_type="LIMIT", limit_price="990", quantity=10).json()
    sell = order(client, auth, acct, symbol="TCS", side="SELL", order_type="LIMIT", limit_price="1010", quantity=10).json()
    assert buy["status"] == "OPEN" and sell["status"] == "OPEN"
    t = ist(2026, 11, 27, 10, 0)
    assert tick(995, t) == [] and tick(1005, t, "TCS") == []
    depth["asks"] = [(991, 100)]                                                              # traded at 990 but the ask is above
    assert tick(990, t) == []
    depth["asks"] = [(989.5, 100)]
    assert tick(990, t) == [f"order {buy['id']} FILLED"]
    assert get_order(client, auth, acct, buy["id"])["avg_price"] == "989.50"                 # better than the limit
    depth["asks"] = []
    assert tick(1012, t, "TCS") == [f"order {sell['id']} FILLED"]
    assert get_order(client, auth, acct, sell["id"])["avg_price"] == "1012.00"


# ============================================================================== 7. stop-loss trigger conditions
def test_stop_loss_limit_triggers_then_waits_for_its_limit(client, auth, acct, px):  # noqa: F811
    assert order(client, auth, acct, order_type="SL", trigger_price="1020", limit_price="1015").status_code == 400  # BUY limit < trigger
    r = order(client, auth, acct, order_type="SL", trigger_price="1020", limit_price="1025", quantity=10).json()
    assert r["status"] == "TRIGGER_PENDING" and r["trigger_price"] == "1020.00" and r["limit_price"] == "1025.00"
    t = ist(2026, 11, 27, 10, 0)
    assert tick(1015, t) == []
    assert tick(1030, t) == [f"order {r['id']} TRIGGERED"]                                   # triggered, but above the limit
    o = get_order(client, auth, acct, r["id"])
    assert o["status"] == "OPEN" and o["triggered_at"] and o["filled_quantity"] == 0
    assert tick(1024, t) == [f"order {r['id']} FILLED"]
    assert get_order(client, auth, acct, r["id"])["avg_price"] == "1024.00"
    assert kinds(r["id"]) == ["ORDER_PLACED", "ORDER_TRIGGERED", "ORDER_FILLED"]


def test_stop_loss_market_exit_closes_the_position(client, auth, acct, px):  # noqa: F811
    order(client, auth, acct, quantity=10)
    sl = order(client, auth, acct, side="SELL", order_type="SL-M", trigger_price="980", quantity=10, product="INTRADAY").json()
    assert sl["status"] == "TRIGGER_PENDING" and sl["reduce_only"] is True
    t = ist(2026, 11, 27, 10, 0)
    assert tick(985, t) == []
    assert tick(975, t) == [f"order {sl['id']} FILLED"]                                       # gap below the trigger: observed price
    assert positions(client, auth, acct) == []
    tr = client.get(f"/api/accounts/{acct}/trades", headers=auth).json()[0]
    assert tr["exit_reason"] == "STOP_LOSS" and tr["exit_price"] == "975.00" and tr["order_id"] == sl["id"]
    assert balance(client, auth, acct) == D("1000000") + D(tr["net_pnl"])                   # ledger invariant still exact


# ============================================================================== 8. insufficient paper balance
def test_insufficient_funds_at_placement_and_at_fill(client, auth, acct, px, market_clock):  # noqa: F811
    big = order(client, auth, acct, quantity=2000).json()
    assert big["status"] == "REJECTED" and big["reject_reason"] == "Insufficient virtual funds"
    lim = order(client, auth, acct, order_type="LIMIT", limit_price="990", quantity=900).json()   # 8.9 lakh: affordable now
    assert lim["status"] == "OPEN"
    client.post(f"/api/accounts/{acct}/withdraw", json={"amount": "500000"}, headers=auth)
    assert tick(985, ist(2026, 11, 27, 10, 0)) == [f"order {lim['id']} REJECTED"]
    o = get_order(client, auth, acct, lim["id"])
    assert o["status"] == "REJECTED" and o["reject_reason"] == "Insufficient virtual funds" and o["filled_quantity"] == 0
    assert positions(client, auth, acct) == [] and balance(client, auth, acct) == D("500000")
    assert client.get("/api/notifications", headers=auth).json()["items"][-1]["title"] == "Order rejected"


# ============================================================================== 9. cancellation and expiration
def test_cancel_and_expire(client, auth, acct, px, market_clock):  # noqa: F811
    lim = order(client, auth, acct, order_type="LIMIT", limit_price="900", quantity=5).json()
    c = client.post(f"/api/accounts/{acct}/orders/{lim['id']}/cancel", headers=auth).json()
    assert c["status"] == "CANCELLED" and c["cancellable"] is False
    assert client.post(f"/api/accounts/{acct}/orders/{lim['id']}/cancel", headers=auth).status_code == 400
    filled = order(client, auth, acct, quantity=1).json()
    assert client.post(f"/api/accounts/{acct}/orders/{filled['id']}/cancel", headers=auth).status_code == 400
    assert tick(800, ist(2026, 11, 27, 10, 0)) == []                                          # a cancelled order never fills

    market_clock(FRI_EVENING)
    amo = order(client, auth, acct, symbol="TCS", order_type="LIMIT", limit_price="900", quantity=5).json()
    with SessionLocal() as db:
        assert engine.expire_orders(db, ist(2026, 11, 30, 10, 0)) == 0                       # Monday: still its session
        assert engine.expire_orders(db, MON_CLOSE + dt.timedelta(seconds=1)) == 1
        assert engine.expire_orders(db, MON_CLOSE + dt.timedelta(hours=1)) == 0
    o = get_order(client, auth, acct, amo["id"])
    assert o["status"] == "EXPIRED" and "expired" in o["reject_reason"]
    assert kinds(amo["id"])[-1] == "ORDER_EXPIRED" and kinds(lim["id"]) == ["ORDER_PLACED", "ORDER_CANCELLED"]


# ============================================================================== 10. partial execution
def test_partial_fills_against_visible_depth(client, auth, acct, px, depth):  # noqa: F811
    depth["asks"] = [(1000, 30), (1000.5, 20)]
    r = order(client, auth, acct, quantity=100).json()
    assert r["status"] == "PARTIALLY_FILLED" and r["filled_quantity"] == 50 and r["remaining_quantity"] == 50
    assert r["avg_price"] == "1000.20"                                                        # (30 x 1000 + 20 x 1000.5) / 50
    p = positions(client, auth, acct)[0]
    assert p["quantity"] == 50
    after_first = balance(client, auth, acct)
    assert after_first < D("1000000") - D("50000")                                           # only the filled part is paid for
    depth["asks"] = [(1001, 100)]
    assert tick(1001, ist(2026, 11, 27, 9, 31)) == [f"order {r['id']} FILLED"]
    o = get_order(client, auth, acct, r["id"])
    assert o["status"] == "FILLED" and o["filled_quantity"] == 100 and o["avg_price"] == "1000.60"
    assert [f["quantity"] for f in o["fills"]] == [50, 50] and [f["price"] for f in o["fills"]] == ["1000.20", "1001.00"]
    p = positions(client, auth, acct)[0]
    assert p["quantity"] == 100 and D(p["entry_value"]) == D("100060.00")                    # one position, averaged
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Position)) == 1
        assert db.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.entry_type == "ORDER_FILL")) == 2
    assert kinds(r["id"]) == ["ORDER_PARTIAL", "ORDER_FILLED"]


def test_cancelling_a_partial_order_keeps_what_was_filled(client, auth, acct, px, depth):  # noqa: F811
    depth["asks"] = [(1000, 40)]
    r = order(client, auth, acct, quantity=100).json()
    c = client.post(f"/api/accounts/{acct}/orders/{r['id']}/cancel", headers=auth).json()
    assert c["status"] == "CANCELLED" and c["filled_quantity"] == 40
    assert positions(client, auth, acct)[0]["quantity"] == 40


# ============================================================================== 11. missing or stale live market data
def test_execution_quote_refuses_previous_session_prices(monkeypatch):
    inst = Instrument(exchange="NSE", symbol="RELIANCE", trading_symbol="RELIANCE-EQ", token="2885", instrument_type="EQ", lot_size=1)
    runtime.store._ticks.clear(); runtime.store._at.clear()
    rows = {"row": None}
    monkeypatch.setattr(pricing, "_full_quote", lambda i: rows["row"])
    with pytest.raises(pricing.PriceUnavailable, match="closed"):
        pricing.execution_quote(inst, FRI_EVENING)
    with pytest.raises(pricing.PriceUnavailable, match="No live quote"):
        pricing.execution_quote(inst, FRI_OPEN)                                               # broker unreachable
    runtime.store.update(Tick("2885", "RELIANCE", "NSE", 999.0, 0, ist(2026, 11, 26, 15, 29), time.time()))   # Thursday's last tick
    rows["row"] = {"symbolToken": "2885", "ltp": 999.0, "exchTradeTime": "26-Nov-2026 15:29:59"}             # broker: previous close
    with pytest.raises(pricing.PriceUnavailable, match="previous close"):
        pricing.execution_quote(inst, FRI_OPEN)
    rows["row"] = {"symbolToken": "2885", "ltp": 1004.5, "exchTradeTime": "27-Nov-2026 09:29:58",
                   "depth": {"buy": [{"price": 1004.4, "quantity": 120}], "sell": [{"price": 1004.6, "quantity": 80}, {"price": 0, "quantity": 5}]}}
    q = pricing.execution_quote(inst, FRI_OPEN)
    assert q.ltp == D("1004.5") and q.source == "rest" and q.bids == ((D("1004.4"), 120),) and q.asks == ((D("1004.6"), 80),)
    runtime.store.update(Tick("2885", "RELIANCE", "NSE", 1005.0, 0, ist(2026, 11, 27, 9, 29, 59), time.time()))
    assert pricing.execution_quote(inst, FRI_OPEN).source == "tick"                         # today's tick wins
    runtime.store._ticks.clear(); runtime.store._at.clear()


def test_no_fresh_data_keeps_queued_orders_pending(client, auth, acct, px, market_clock, monkeypatch):  # noqa: F811
    market_clock(FRI_EVENING)
    oid = order(client, auth, acct, quantity=10).json()["id"]
    market_clock(MON_OPEN)

    def down(inst, at=None):
        raise pricing.PriceUnavailable("No trade yet in the current session")

    monkeypatch.setattr(pricing, "execution_quote", down)
    assert poller.tick() == 0
    assert get_order(client, auth, acct, oid)["status"] == "PENDING" and positions(client, auth, acct) == []


# ============================================================================== 12. duplicate execution prevention
def test_same_fill_can_never_happen_twice(client, auth, acct, px):  # noqa: F811
    r = order(client, auth, acct, order_type="LIMIT", limit_price="990", quantity=10).json()
    with SessionLocal() as db:
        assert engine._fill(db, r["id"], 0, 10, D("989")) == f"order {r['id']} FILLED"
        assert engine._fill(db, r["id"], 0, 10, D("989")) is None                           # same expected state: no-op
    errors = []

    def worker():
        try:
            with SessionLocal() as db:
                engine.process_price(db, iid(), D("980"), at=ist(2026, 11, 27, 10, 0))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    r2 = order(client, auth, acct, symbol="TCS", order_type="LIMIT", limit_price="990", quantity=10).json()
    threads = [threading.Thread(target=lambda: tick(980, ist(2026, 11, 27, 10, 0), "TCS")) for _ in range(6)]
    threads += [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with SessionLocal() as db:
        fills = db.scalar(select(func.count()).select_from(TradeLog).where(TradeLog.order_id == r2["id"]))
        ledger = db.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.idempotency_key.like(f"order-{r2['id']}-%")))
        assert fills == 1 and ledger == 1
        assert db.get(Order, r2["id"]).filled_quantity == 10
    assert sum(p["quantity"] for p in positions(client, auth, acct)) == 20


# ============================================================================== 13. application restart with pending orders
def test_restart_with_pending_orders(client, auth, acct, px, market_clock, monkeypatch):  # noqa: F811
    market_clock(FRI_EVENING)
    amo = order(client, auth, acct, quantity=10).json()
    lim = order(client, auth, acct, symbol="TCS", order_type="LIMIT", limit_price="995", quantity=10).json()
    market_clock(SAT)                                                                         # "restart" over the weekend
    assert poller.tick() == 0
    market_clock(MON_OPEN)
    monkeypatch.setattr(pricing, "execution_quote", lambda inst, at=None: pricing.ExecQuote(D("990"), MON_OPEN.astimezone(dt.timezone.utc), "test"))
    assert poller.tick() == 2                                                                 # both instruments evaluated once
    assert get_order(client, auth, acct, amo["id"])["status"] == "FILLED"
    assert get_order(client, auth, acct, lim["id"])["status"] == "FILLED"
    assert poller.tick() == 2 and len(positions(client, auth, acct)) == 2                    # running again changes nothing
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TradeLog)) == 2


def test_legacy_orders_are_migrated_once(client):
    from app.database import migrations

    from tests.conftest import register

    register(client, "legacy@example.com")
    acc_id = client.post("/api/accounts", json={"name": "Legacy", "initial_capital": "1000"},
                         headers=register(client, "legacy2@example.com")).json()["id"]
    with SessionLocal() as db:
        db.add(Instrument(exchange="NSE", symbol="X", trading_symbol="X-EQ", token="1", instrument_type="EQ", lot_size=1))
        db.commit()
        inst_id = db.scalar(select(Instrument.id).where(Instrument.symbol == "X"))
    with db_engine.begin() as c:
        for st, ot, lp, rr in (("EXECUTED", "MARKET", None, None), ("PENDING", "TRIGGER", 105, None), ("PENDING", "LIMIT", 95, None),
                               ("CANCELLED", "LIMIT", 90, "Day order expired"), ("CANCELLED", "LIMIT", 90, None)):
            c.execute(text("INSERT INTO orders (account_id, instrument_id, side, order_type, product, quantity, limit_price, status, "
                           "reject_reason, validity, created_at, filled_quantity, after_market, reduce_only) "
                           "VALUES (:a, :i, 'BUY', :ot, 'DELIVERY', 5, :lp, :st, :rr, 'DAY', '2026-01-01', 0, 0, 0)"),   # column defaults after ensure_columns()
                      {"a": acc_id, "i": inst_id, "ot": ot, "lp": lp, "st": st, "rr": rr})
    migrations.run(db_engine)
    migrations.run(db_engine)                                                                 # idempotent
    with SessionLocal() as db:
        rows = [(o.status, o.order_type, o.filled_quantity, o.limit_price, o.trigger_price) for o in db.scalars(select(Order).order_by(Order.id))]
    assert rows == [("FILLED", "MARKET", 5, None, None), ("TRIGGER_PENDING", "SL-M", 0, None, D("105.00")),
                    ("OPEN", "LIMIT", 0, D("95.00"), None), ("EXPIRED", "LIMIT", 0, D("90.00"), None), ("CANCELLED", "LIMIT", 0, D("90.00"), None)]


# ============================================================================== exits, order book, notifications API
def test_exit_while_closed_is_queued_and_executes_at_the_open(client, auth, acct, px, market_clock):  # noqa: F811
    order(client, auth, acct, quantity=10)
    pid = positions(client, auth, acct)[0]["id"]
    market_clock(FRI_EVENING)
    r = client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth).json()
    assert r["trade"] is None and r["order"]["status"] == "PENDING" and r["order"]["reduce_only"] is True
    assert positions(client, auth, acct)[0]["quantity"] == 10                                # nothing sold at Friday's price
    assert tick(1020, MON_OPEN) == [f"order {r['order']['id']} FILLED"]
    assert positions(client, auth, acct) == []
    tr = client.get(f"/api/accounts/{acct}/trades", headers=auth).json()[0]
    assert tr["exit_price"] == "1020.00" and tr["order_id"] == r["order"]["id"]


def test_order_book_filters_and_detail(client, auth, acct, px, market_clock):  # noqa: F811
    filled = order(client, auth, acct, quantity=1).json()
    opened = order(client, auth, acct, order_type="LIMIT", limit_price="900", quantity=1).json()
    rejected = order(client, auth, acct, quantity=5000).json()
    cancelled = order(client, auth, acct, symbol="TCS", order_type="LIMIT", limit_price="900", quantity=1).json()
    client.post(f"/api/accounts/{acct}/orders/{cancelled['id']}/cancel", headers=auth)
    market_clock(FRI_EVENING)
    pending = order(client, auth, acct, symbol="INFY", quantity=1).json()
    ids = lambda st: [o["id"] for o in client.get(f"/api/accounts/{acct}/orders?status={st}", headers=auth).json()]  # noqa: E731
    assert ids("executed") == [filled["id"]] and ids("open") == [opened["id"]] and ids("pending") == [pending["id"]]
    assert ids("rejected") == [rejected["id"]] and ids("cancelled") == [cancelled["id"]] and len(ids("all")) == 5
    d = get_order(client, auth, acct, filled["id"])
    assert d["fills"][0]["quantity"] == 1 and d["fills"][0]["price"] == "1000.00" and d["history"][-1]["kind"] == "ORDER_FILLED"
    assert client.get(f"/api/accounts/{acct}/orders/99999", headers=auth).status_code == 404


def test_notifications_catch_up_and_mark_read(client, auth, acct, px):  # noqa: F811
    order(client, auth, acct, quantity=1)
    first = client.get("/api/notifications", headers=auth).json()
    assert first["unread"] == 1 and first["latest_id"] == first["items"][-1]["id"]
    order(client, auth, acct, order_type="LIMIT", limit_price="900", quantity=1)
    new = client.get(f"/api/notifications?after_id={first['latest_id']}", headers=auth).json()["items"]
    assert [n["title"] for n in new] == ["Order placed successfully"]
    client.post("/api/notifications/read", json={}, headers=auth)
    assert client.get("/api/notifications", headers=auth).json()["unread"] == 0


def test_order_settings_roundtrip(client, auth, acct):  # noqa: F811
    s = client.get(f"/api/accounts/{acct}/order-settings", headers=auth).json()
    assert s["after_hours_mode"] == "QUEUE" and s["slippage_pct"] is None
    s = client.put(f"/api/accounts/{acct}/order-settings", json={"after_hours_mode": "REJECT", "slippage_pct": "0.05"}, headers=auth).json()
    assert s["after_hours_mode"] == "REJECT" and s["slippage_pct"] == "0.05"
    assert client.put(f"/api/accounts/{acct}/order-settings", json={"after_hours_mode": "MAYBE"}, headers=auth).status_code == 422


def test_frontend_cannot_fill_an_order(client, auth, acct, px):  # noqa: F811
    """There is no API that sets an order's status or price: a client can place, read and cancel, nothing else."""
    lim = order(client, auth, acct, order_type="LIMIT", limit_price="900", quantity=1).json()
    for method in ("put", "patch"):
        r = getattr(client, method)(f"/api/accounts/{acct}/orders/{lim['id']}", json={"status": "FILLED", "exec_price": "1"}, headers=auth)
        assert r.status_code == 405
    assert get_order(client, auth, acct, lim["id"])["status"] == "OPEN"
