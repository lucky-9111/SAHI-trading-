from datetime import datetime
from decimal import Decimal

import pytest

from app.database.session import SessionLocal
from app.market_data.instrument_master import sync_nse_equities
from app.trading import engine, market_status, pricing
from app.trading.charges import estimate_charges
from tests.conftest import register
from tests.test_instruments import ROWS

D = Decimal


@pytest.fixture()
def px(monkeypatch):
    """Controllable price feed (the engine never invents prices; tests supply them)."""
    state = {"price": D("1000"), "open": True, "fail": False}

    def fake(inst, max_age=3.0):
        if state["fail"]:
            raise pricing.PriceUnavailable("feed down")
        return pricing.PriceQuote(state["price"], datetime.now(), state["open"])

    def fake_exec(inst, at=None):
        if state["fail"]:
            raise pricing.PriceUnavailable("feed down")
        return pricing.ExecQuote(state["price"], market_status.now(), "test")

    monkeypatch.setattr(pricing, "get_price", fake)
    monkeypatch.setattr(pricing, "execution_quote", fake_exec)
    return state


@pytest.fixture()
def acct(client, auth):
    with SessionLocal() as db:
        sync_nse_equities(db, ROWS)
    r = client.post("/api/accounts", json={"name": "Main", "initial_capital": "1000000"}, headers=auth)
    return r.json()["id"]


def order(client, auth, acct, **kw):
    body = {"symbol": "RELIANCE", "side": "BUY", "order_type": "MARKET", "quantity": 100, **kw}
    return client.post(f"/api/accounts/{acct}/orders", json=body, headers=auth)


def balance(client, auth, acct):
    return D(next(a for a in client.get("/api/accounts", headers=auth).json() if a["id"] == acct)["balance"])


def positions(client, auth, acct):
    return client.get(f"/api/accounts/{acct}/positions", headers=auth).json()


def test_charges_are_estimated_per_leg():
    buy = estimate_charges("INTRADAY", "BUY", D("100000"))
    sell = estimate_charges("INTRADAY", "SELL", D("100000"))
    assert sell > buy > 0  # STT only on the sell leg
    assert estimate_charges("DELIVERY", "BUY", D("100000")) > buy


def test_market_buy_debits_funds_and_opens_position(client, auth, acct, px):
    r = order(client, auth, acct, stop_loss="950", target="1100")
    assert r.status_code == 201 and r.json()["status"] == "FILLED" and r.json()["exec_price"] == "1000.00"
    ch = estimate_charges("INTRADAY", "BUY", D("100000"))
    assert balance(client, auth, acct) == D("1000000") - D("100000") - ch
    p = positions(client, auth, acct)
    assert len(p) == 1 and p[0]["quantity"] == 100 and p[0]["avg_price"] == "1000.00"
    assert p[0]["stop_loss"] == "950.00" and p[0]["unrealized_pnl"] == "0.00"


def test_manual_exit_credits_funds_and_records_trade(client, auth, acct, px):
    order(client, auth, acct)
    px["price"] = D("1010")
    pid = positions(client, auth, acct)[0]["id"]
    t = client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth).json()["trade"]
    assert D(t["gross_pnl"]) == D("1000.00") and t["exit_reason"] == "MANUAL"
    assert D(t["net_pnl"]) == D(t["gross_pnl"]) - D(t["charges"])
    # Ledger invariant: balance change == net P&L exactly
    assert balance(client, auth, acct) == D("1000000") + D(t["net_pnl"])
    assert positions(client, auth, acct) == []


def test_short_sell_profit_when_price_falls(client, auth, acct, px):
    order(client, auth, acct, side="SELL", stop_loss="1050", target="900")
    px["price"] = D("990")
    pid = positions(client, auth, acct)[0]["id"]
    t = client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth).json()["trade"]
    assert D(t["gross_pnl"]) == D("1000.00")
    assert balance(client, auth, acct) == D("1000000") + D(t["net_pnl"])


def test_partial_exit_then_full_exit_is_exact(client, auth, acct, px):
    order(client, auth, acct, quantity=101)
    pid = positions(client, auth, acct)[0]["id"]
    px["price"] = D("1003.33")
    t1 = client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={"quantity": 40}, headers=auth).json()["trade"]
    assert positions(client, auth, acct)[0]["quantity"] == 61
    t2 = client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth).json()["trade"]
    assert positions(client, auth, acct) == []
    net = D(t1["net_pnl"]) + D(t2["net_pnl"])
    assert balance(client, auth, acct) == D("1000000") + net  # no paisa lost to rounding
    assert client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth).status_code == 400


def test_cannot_exit_more_than_open(client, auth, acct, px):
    order(client, auth, acct)
    pid = positions(client, auth, acct)[0]["id"]
    r = client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={"quantity": 101}, headers=auth)
    assert r.status_code == 400


def test_invalid_stop_loss_direction_rejected(client, auth, acct, px):
    assert order(client, auth, acct, stop_loss="1010").status_code == 400  # BUY SL above entry
    assert order(client, auth, acct, side="SELL", stop_loss="990").status_code == 400
    assert order(client, auth, acct, target="990").status_code == 400
    assert positions(client, auth, acct) == []
    assert balance(client, auth, acct) == D("1000000")


def test_insufficient_funds_rejects_order_without_touching_balance(client, auth, acct, px):
    r = order(client, auth, acct, quantity=2000)  # 20 lakh > 10 lakh
    assert r.json()["status"] == "REJECTED" and "Insufficient" in r.json()["reject_reason"]
    assert balance(client, auth, acct) == D("1000000")
    assert positions(client, auth, acct) == []


def test_no_price_means_no_market_order(client, auth, acct, px):
    px["fail"] = True
    client.put(f"/api/accounts/{acct}/order-settings", json={"after_hours_mode": "QUEUE"}, headers=auth)
    r = order(client, auth, acct).json()                                   # queue mode: waits for the first fresh price
    assert r["status"] == "PENDING" and r["filled_quantity"] == 0 and r["exec_price"] is None
    client.put(f"/api/accounts/{acct}/order-settings", json={"after_hours_mode": "REJECT"}, headers=auth)
    r = order(client, auth, acct).json()                                   # reject mode: recorded as rejected, never filled
    assert r["status"] == "REJECTED" and "No fresh market price" in r["reject_reason"]
    assert positions(client, auth, acct) == [] and balance(client, auth, acct) == D("1000000")


def test_duplicate_idempotency_key_does_not_double_execute(client, auth, acct, px):
    a = order(client, auth, acct, idempotency_key="k1").json()
    b = order(client, auth, acct, idempotency_key="k1").json()
    assert a["id"] == b["id"]
    assert positions(client, auth, acct)[0]["quantity"] == 100


def test_adding_to_position_averages_price(client, auth, acct, px):
    order(client, auth, acct)
    px["price"] = D("1100")
    order(client, auth, acct)
    p = positions(client, auth, acct)[0]
    assert p["quantity"] == 200 and p["avg_price"] == "1050.00"


def test_stop_loss_gap_fills_at_observed_price_not_sl_level(client, auth, acct, px):
    order(client, auth, acct, stop_loss="950", target="1100")
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        assert engine.process_price(db, iid, D("960")) == []  # above SL: nothing happens
        ev = engine.process_price(db, iid, D("900"))  # gap down through SL
    assert ev and "STOP_LOSS" in ev[0]
    t = client.get(f"/api/accounts/{acct}/trades", headers=auth).json()[0]
    assert t["exit_reason"] == "STOP_LOSS" and t["exit_price"] == "900.00"  # worse than 950
    assert D(t["gross_pnl"]) == D("-10000.00")


def test_same_price_update_cannot_close_position_twice(client, auth, acct, px):
    order(client, auth, acct, stop_loss="950")
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        first = engine.process_price(db, iid, D("940"))
        second = engine.process_price(db, iid, D("940"))
    assert len(first) == 1 and second == []
    assert len(client.get(f"/api/accounts/{acct}/trades", headers=auth).json()) == 1


def test_target_hit_closes_long_and_short(client, auth, acct, px):
    order(client, auth, acct, target="1050")
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        assert "TARGET" in engine.process_price(db, iid, D("1051"))[0]
    order(client, auth, acct, side="SELL", target="950", stop_loss="1100")
    with SessionLocal() as db:
        assert "TARGET" in engine.process_price(db, iid, D("949"))[0]


def test_limit_order_stays_pending_then_fills_and_can_cancel(client, auth, acct, px):
    r = order(client, auth, acct, order_type="LIMIT", limit_price="980").json()
    assert r["status"] == "OPEN"
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        assert engine.process_price(db, iid, D("985")) == []
        ev = engine.process_price(db, iid, D("975"))  # price improved below limit
        assert ev and engine.process_price(db, iid, D("970")) == []  # cannot fill twice
    o = client.get(f"/api/accounts/{acct}/orders", headers=auth).json()[0]
    assert o["status"] == "FILLED" and o["exec_price"] == "975.00"
    r2 = order(client, auth, acct, order_type="LIMIT", limit_price="900").json()
    c = client.post(f"/api/accounts/{acct}/orders/{r2['id']}/cancel", headers=auth)
    assert c.json()["status"] == "CANCELLED"
    assert client.post(f"/api/accounts/{acct}/orders/{r2['id']}/cancel", headers=auth).status_code == 400


def test_trigger_buy_waits_for_price_to_rise_and_fills_at_observed_price(client, auth, acct, px):
    r = order(client, auth, acct, order_type="TRIGGER", limit_price="1020").json()
    assert r["status"] == "TRIGGER_PENDING" and r["validity"] == "DAY" and r["order_type"] == "SL-M" and r["trigger_price"] == "1020.00"
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        assert engine.process_price(db, iid, D("1010")) == []  # below trigger: nothing
        assert engine.process_price(db, iid, D("1035"))  # gapped through the trigger
        assert engine.process_price(db, iid, D("1040")) == []  # cannot fill twice
    o = client.get(f"/api/accounts/{acct}/orders", headers=auth).json()[0]
    assert o["status"] == "FILLED" and o["exec_price"] == "1035.00"


def test_trigger_sell_fires_on_fall_and_direction_is_validated(client, auth, acct, px):
    assert order(client, auth, acct, side="SELL", order_type="TRIGGER", limit_price="1010").status_code == 400
    assert order(client, auth, acct, order_type="TRIGGER", limit_price="990").status_code == 400
    assert order(client, auth, acct, order_type="TRIGGER").status_code == 400  # trigger price required
    assert order(client, auth, acct, side="SELL", order_type="TRIGGER", limit_price="980").json()["status"] == "TRIGGER_PENDING"
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        assert engine.process_price(db, iid, D("985")) == []
        assert engine.process_price(db, iid, D("975"))
    assert positions(client, auth, acct)[0]["side"] == "SELL"


def test_day_orders_expire_but_gtt_orders_stay(client, auth, acct, px):
    day = order(client, auth, acct, order_type="LIMIT", limit_price="900", product="DELIVERY").json()
    gtt = order(client, auth, acct, order_type="LIMIT", limit_price="880", product="DELIVERY", validity="GTT").json()
    assert day["expires_at"] is not None and gtt["expires_at"] is None and gtt["validity"] == "GTT"
    from datetime import timedelta
    with SessionLocal() as db:
        assert engine.expire_orders(db, market_status.now()) == 0  # session has not ended yet
        assert engine.expire_orders(db, market_status.now() + timedelta(days=5)) == 1
    st = {o["id"]: o for o in client.get(f"/api/accounts/{acct}/orders", headers=auth).json()}
    assert st[day["id"]]["status"] == "EXPIRED" and st[day["id"]]["reject_reason"] == "Day order expired at market close"
    assert st[gtt["id"]]["status"] == "OPEN"


def test_intraday_gtt_is_rejected(client, auth, acct, px):
    r = order(client, auth, acct, order_type="LIMIT", limit_price="900", validity="GTT")
    assert r.status_code == 400 and "day only" in r.json()["detail"]


def test_session_close_rolls_to_next_weekday():
    from datetime import datetime
    from app.trading.pricing import IST, session_close
    assert session_close(datetime(2026, 11, 26, 11, 0, tzinfo=IST)).date().isoformat() == "2026-11-26"  # Thu, open
    assert session_close(datetime(2026, 11, 26, 18, 0, tzinfo=IST)).date().isoformat() == "2026-11-27"  # Thu after close
    assert session_close(datetime(2026, 11, 27, 18, 0, tzinfo=IST)).date().isoformat() == "2026-11-30"  # Fri -> Mon
    assert session_close(datetime(2026, 11, 28, 10, 0, tzinfo=IST)).date().isoformat() == "2026-11-30"  # Sat -> Mon


def test_marketable_limit_fills_immediately(client, auth, acct, px):
    r = order(client, auth, acct, order_type="LIMIT", limit_price="1005").json()
    assert r["status"] == "FILLED" and r["exec_price"] == "1000.00"


def test_preview_calculates_quantity_from_risk(client, auth, acct, px):
    r = client.post(f"/api/accounts/{acct}/orders/preview", headers=auth,
                    json={"symbol": "RELIANCE", "side": "BUY", "order_type": "LIMIT", "limit_price": "1000",
                          "stop_loss": "950", "target": "1100"}).json()
    assert r["max_risk_amount"] == "10000.00" and r["suggested_quantity"] == 200
    assert r["risk_per_share"] == "50.00" and r["total_risk"] == "10000.00"
    assert r["potential_reward"] == "20000.00" and r["risk_reward"] == "2.00" and r["order_value"] == "200000.00"
    assert r["errors"] == []
    m = client.post(f"/api/accounts/{acct}/orders/preview", headers=auth,
                    json={"symbol": "RELIANCE", "side": "BUY", "quantity": 300, "stop_loss": "1010"}).json()
    assert any("below the entry" in e for e in m["errors"])


def test_manual_quantity_shows_actual_risk(client, auth, acct, px):
    r = client.post(f"/api/accounts/{acct}/orders/preview", headers=auth,
                    json={"symbol": "RELIANCE", "side": "BUY", "quantity": 500, "stop_loss": "950"}).json()
    assert r["total_risk"] == "25000.00" and any("exceeds" in w for w in r["warnings"])


def test_strict_daily_loss_blocks_new_orders(client, auth, acct, px):
    client.put(f"/api/accounts/{acct}/risk", headers=auth, json={
        "risk_per_trade_pct": "1", "max_daily_loss": "5000", "max_open_positions": 5, "strict_protection": True})
    order(client, auth, acct)
    px["price"] = D("900")  # lose ~10k
    pid = positions(client, auth, acct)[0]["id"]
    client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth)
    r = order(client, auth, acct)
    assert r.status_code == 400 and "Daily loss limit" in r.json()["detail"]


def test_max_open_positions_enforced(client, auth, acct, px):
    client.put(f"/api/accounts/{acct}/risk", headers=auth, json={
        "risk_per_trade_pct": "1", "max_open_positions": 1, "strict_protection": False})
    order(client, auth, acct)
    assert order(client, auth, acct, symbol="TCS").status_code == 400


def test_modify_stop_loss_and_target(client, auth, acct, px):
    order(client, auth, acct)
    pid = positions(client, auth, acct)[0]["id"]
    ok = client.patch(f"/api/accounts/{acct}/positions/{pid}", json={"stop_loss": "970", "target": "1080"}, headers=auth)
    assert ok.json()["stop_loss"] == "970.00" and ok.json()["target"] == "1080.00"
    bad = client.patch(f"/api/accounts/{acct}/positions/{pid}", json={"stop_loss": "1020"}, headers=auth)
    assert bad.status_code == 400


def test_other_users_cannot_touch_account_trading(client, auth, acct, px):
    order(client, auth, acct)
    h2 = register(client, "other@example.com")
    pid = positions(client, auth, acct)[0]["id"]
    assert client.get(f"/api/accounts/{acct}/positions", headers=h2).status_code == 404
    assert client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=h2).status_code == 404
    assert order(client, h2, acct).status_code == 404


def test_dashboard_reflects_real_trades(client, auth, acct, px):
    order(client, auth, acct)
    px["price"] = D("1010")
    d = client.get(f"/api/accounts/{acct}/dashboard", headers=auth).json()
    assert d["stats"]["open_positions"] == 1 and D(str(d["pnl"]["unrealized"])) == D("1000.00")
    pid = positions(client, auth, acct)[0]["id"]
    client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth)
    d = client.get(f"/api/accounts/{acct}/dashboard", headers=auth).json()
    assert d["stats"]["total_trades"] == 1 and d["stats"]["win_rate"] == 100.0
    assert D(str(d["capital"]["available_balance"])) == D(str(d["capital"]["total_virtual_capital"]))
