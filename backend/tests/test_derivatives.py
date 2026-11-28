from datetime import date
from decimal import Decimal

import pytest

from app.database.session import SessionLocal
from app.market_data import angel
from app.market_data.instrument_master import sync_derivatives
from app.trading import pricing
from app.trading.charges import FUT_MARGIN_PCT, OPT_SELL_MARGIN_PCT, estimate_charges
from tests.test_trading import acct, balance, order, positions, px  # noqa: F401  (shared fixtures)

D = Decimal
ROWS = [
    {"token": "50001", "symbol": "NIFTY30DEC2099FUT", "name": "NIFTY", "expiry": "30DEC2099", "strike": "-1.000000",
     "lotsize": "75", "instrumenttype": "FUTIDX", "exch_seg": "NFO", "tick_size": "10.000000"},
    {"token": "50002", "symbol": "NIFTY30DEC209926000CE", "name": "NIFTY", "expiry": "30DEC2099", "strike": "2600000.000000",
     "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO", "tick_size": "5.000000"},
    {"token": "50003", "symbol": "NIFTY30DEC209926000PE", "name": "NIFTY", "expiry": "30DEC2099", "strike": "2600000.000000",
     "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO", "tick_size": "5.000000"},
    {"token": "50004", "symbol": "NIFTY30DEC209926100CE", "name": "NIFTY", "expiry": "30DEC2099", "strike": "2610000.000000",
     "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO", "tick_size": "5.000000"},
    {"token": "50005", "symbol": "RELIANCE30DEC2099FUT", "name": "RELIANCE", "expiry": "30DEC2099", "strike": "-1.000000",
     "lotsize": "500", "instrumenttype": "FUTSTK", "exch_seg": "NFO", "tick_size": "5.000000"},
    {"token": "50006", "symbol": "NIFTY01JAN2020FUT", "name": "NIFTY", "expiry": "01JAN2020", "strike": "-1.000000",
     "lotsize": "75", "instrumenttype": "FUTIDX", "exch_seg": "NFO", "tick_size": "10.000000"},
]
FUT, CE, PE = "NIFTY30DEC2099FUT", "NIFTY30DEC209926000CE", "NIFTY30DEC209926000PE"


@pytest.fixture()
def fno(acct):  # noqa: F811
    with SessionLocal() as db:
        sync_derivatives(db, ROWS, today=date(2026, 11, 26))
    return acct


def fo_order(client, auth, acct, symbol, **kw):  # noqa: F811
    body = {"symbol": symbol, "exchange": "NFO", "side": "BUY", "order_type": "MARKET", "product": "NRML",
            "quantity": 75, **kw}
    return client.post(f"/api/accounts/{acct}/orders", json=body, headers=auth)


def test_sync_parses_contracts_and_skips_expired(client, auth, fno):
    with SessionLocal() as db:
        from sqlalchemy import select
        from app.models.market import Instrument
        ce = db.scalar(select(Instrument).where(Instrument.symbol == CE))
        assert ce.strike == D("26000.00") and ce.option_type == "CE" and ce.underlying == "NIFTY"
        assert ce.expiry == date(2099, 12, 30) and ce.lot_size == 75 and ce.instrument_type == "OPT"
        assert db.scalar(select(Instrument).where(Instrument.symbol == "NIFTY01JAN2020FUT")) is None
        assert sync_derivatives(db, ROWS, today=date(2026, 11, 26)) == 5  # idempotent


def test_future_requires_whole_lots(client, auth, fno, px):  # noqa: F811
    px["price"] = D("26000")
    r = fo_order(client, auth, fno, FUT, quantity=50)
    assert r.status_code == 400 and "lot size" in r.json()["detail"]
    assert positions(client, auth, fno) == []


def test_future_blocks_margin_not_full_value_and_round_trip_is_exact(client, auth, fno, px):  # noqa: F811
    px["price"] = D("26000")
    r = fo_order(client, auth, fno, FUT)
    assert r.json()["status"] == "FILLED"
    notional = D("26000") * 75
    margin = notional * FUT_MARGIN_PCT
    ch = estimate_charges("NRML", "BUY", notional, "FUT")
    assert balance(client, auth, fno) == D("1000000") - margin - ch
    p = positions(client, auth, fno)[0]
    assert p["invested_amount"] == f"{margin:.2f}" and p["avg_price"] == "26000.00" and p["instrument_type"] == "FUT"
    px["price"] = D("26100")
    assert positions(client, auth, fno)[0]["unrealized_pnl"] == "7500.00"  # 100 pts x 75
    t = client.post(f"/api/accounts/{fno}/positions/{p['id']}/exit", json={}, headers=auth).json()["trade"]
    assert t["gross_pnl"] == "7500.00"
    assert balance(client, auth, fno) == D("1000000") + D(t["net_pnl"])


def test_short_future_profits_when_price_falls(client, auth, fno, px):  # noqa: F811
    px["price"] = D("26000")
    fo_order(client, auth, fno, FUT, side="SELL")
    px["price"] = D("25900")
    pid = positions(client, auth, fno)[0]["id"]
    t = client.post(f"/api/accounts/{fno}/positions/{pid}/exit", json={}, headers=auth).json()["trade"]
    assert t["gross_pnl"] == "7500.00" and balance(client, auth, fno) == D("1000000") + D(t["net_pnl"])


def test_long_option_costs_full_premium(client, auth, fno, px):  # noqa: F811
    px["price"] = D("120")
    fo_order(client, auth, fno, CE)
    prem = D("120") * 75
    ch = estimate_charges("NRML", "BUY", prem, "OPT")
    assert balance(client, auth, fno) == D("1000000") - prem - ch
    px["price"] = D("0.05")  # can lose at most the premium
    pid = positions(client, auth, fno)[0]["id"]
    t = client.post(f"/api/accounts/{fno}/positions/{pid}/exit", json={}, headers=auth).json()["trade"]
    assert D(t["gross_pnl"]) == (D("0.05") - D("120")) * 75


def test_writing_option_blocks_margin_on_strike_value(client, auth, fno, px):  # noqa: F811
    px["price"] = D("100")
    r = fo_order(client, auth, fno, PE, side="SELL")
    assert r.json()["status"] == "FILLED"
    margin = D("26000") * 75 * OPT_SELL_MARGIN_PCT
    ch = estimate_charges("NRML", "SELL", D("100") * 75, "OPT")
    assert balance(client, auth, fno) == D("1000000") - margin - ch
    px["price"] = D("80")  # premium decays: writer profits
    pid = positions(client, auth, fno)[0]["id"]
    t = client.post(f"/api/accounts/{fno}/positions/{pid}/exit", json={}, headers=auth).json()["trade"]
    assert t["gross_pnl"] == "1500.00" and balance(client, auth, fno) == D("1000000") + D(t["net_pnl"])


def test_product_rules(client, auth, fno, px):  # noqa: F811
    px["price"] = D("1000")
    assert order(client, auth, fno, product="SWING", side="SELL").status_code == 400  # no short in swing (flat)
    assert order(client, auth, fno, product="SWING").json()["status"] == "FILLED"
    exit_ = order(client, auth, fno, product="SWING", side="SELL").json()             # holding a long: a SELL is an exit order
    assert exit_["status"] == "FILLED" and exit_["reduce_only"] is True
    assert order(client, auth, fno, product="SWING", side="SELL").status_code == 400  # flat again: no short
    assert order(client, auth, fno, product="NRML").status_code == 400  # NRML is F&O only
    assert fo_order(client, auth, fno, FUT, product="DELIVERY").status_code == 400


def test_expired_contract_rejected(client, auth, fno, px):  # noqa: F811
    with SessionLocal() as db:
        from sqlalchemy import select
        from app.models.market import Instrument
        i = db.scalar(select(Instrument).where(Instrument.symbol == FUT))
        i.expiry = date(2020, 1, 1)
        db.commit()
    px["price"] = D("26000")
    r = fo_order(client, auth, fno, FUT)
    assert r.status_code == 400 and "expired" in r.json()["detail"]


def test_preview_suggests_whole_lots_and_warns_about_margin(client, auth, fno, px):  # noqa: F811
    px["price"] = D("26000")
    r = client.post(f"/api/accounts/{fno}/orders/preview", headers=auth, json={
        "symbol": FUT, "exchange": "NFO", "side": "BUY", "product": "NRML", "stop_loss": "25800"}).json()
    # budget 10,000 / (200 x 75 per lot = 15,000) -> 0 lots
    assert r["lot_size"] == 75 and r["suggested_quantity"] == 0
    assert any("margin" in w.lower() for w in r["warnings"])
    r2 = client.post(f"/api/accounts/{fno}/orders/preview", headers=auth, json={
        "symbol": FUT, "exchange": "NFO", "side": "BUY", "product": "NRML", "stop_loss": "25990", "quantity": 75}).json()
    assert r2["required_funds"] is not None and r2["errors"] == []
    r3 = client.post(f"/api/accounts/{fno}/orders/preview", headers=auth, json={
        "symbol": FUT, "exchange": "NFO", "side": "BUY", "product": "NRML", "quantity": 30}).json()
    assert any("lot size" in e for e in r3["errors"])


def test_derivative_expiries_and_chain(client, auth, fno, monkeypatch):  # noqa: F811
    pricing._qcache.clear()
    feed = {"99926000": 26040.0, "50001": 26050.0, "50002": 210.0, "50003": 190.0, "50004": 160.0}

    def fake(exchange_tokens):
        return [{"exchange": ex, "symbolToken": t, "ltp": feed[t], "close": feed[t] - 10, "netChange": 10,
                 "percentChange": 0.1, "tradeVolume": 1} for ex, toks in exchange_tokens.items() for t in toks if t in feed]

    monkeypatch.setattr(angel.provider, "get_market_data", fake)
    e = client.get("/api/derivatives/NIFTY/expiries", headers=auth).json()
    assert e["is_index"] and e["lot_size"] == 75 and e["chart_symbol"] == "NIFTY50" and e["spot"] == "26040.0"
    assert e["futures"][0]["symbol"] == FUT and e["futures"][0]["ltp"] == "26050.0"
    assert e["option_expiries"] == ["2099-12-30"]
    c = client.get("/api/derivatives/NIFTY/chain", params={"expiry": "2099-12-30"}, headers=auth).json()
    assert c["atm_strike"] == "26000.00" and [r["strike"] for r in c["rows"]] == ["26000.00", "26100.00"]
    assert c["rows"][0]["ce"]["symbol"] == CE and c["rows"][0]["pe"]["ltp"] == "190.0"
    assert c["rows"][1]["pe"] is None  # that strike has no PE in the data
    assert client.get("/api/derivatives/NOSUCH/expiries", headers=auth).status_code == 404
    assert client.get("/api/derivatives/RELIANCE/expiries", headers=auth).json()["futures"][0]["lot_size"] == 500


def test_chart_button_targets_the_stock_or_the_fno_underlying(client, auth, fno, px):  # noqa: F811
    px["price"] = D("26000")
    fo_order(client, auth, fno, FUT)
    order(client, auth, fno, quantity=1)  # RELIANCE equity
    orders = {o["symbol"]: o for o in client.get(f"/api/accounts/{fno}/orders", headers=auth).json()}
    assert (orders[FUT]["chart_symbol"], orders[FUT]["chart_exchange"]) == ("NIFTY", "NSE")
    assert (orders["RELIANCE"]["chart_symbol"], orders["RELIANCE"]["chart_exchange"]) == ("RELIANCE", "NSE")
    pos = {p["symbol"]: p for p in positions(client, auth, fno)}
    assert pos[FUT]["chart_symbol"] == "NIFTY" and pos["RELIANCE"]["chart_symbol"] == "RELIANCE"
    t = client.post(f"/api/accounts/{fno}/positions/{pos[FUT]['id']}/exit", json={}, headers=auth).json()["trade"]
    assert t["chart_symbol"] == "NIFTY"


def test_search_offers_index_underlyings_but_not_contracts(client, auth, fno):
    r = client.get("/api/instruments/search", params={"q": "nifty"}, headers=auth).json()
    assert r and r[0]["instrument_type"] == "IDX" and r[0]["symbol"] == "NIFTY"
    assert all(x["instrument_type"] in ("IDX", "EQ") for x in r)


def test_futures_carry_open_interest_and_day_change(client, auth, fno, monkeypatch):  # noqa: F811
    """The futures sheet shows OI and the day's change; OI comes from Angel's FULL quote (opnInterest, may be a float string)."""
    pricing._qcache.clear()

    def fake(exchange_tokens):
        return [{"exchange": ex, "symbolToken": t, "ltp": 26050.0, "close": 26000.0, "netChange": 50.0, "percentChange": 0.19,
                 "tradeVolume": 10, "opnInterest": "31912400.0"} for ex, toks in exchange_tokens.items() for t in toks]

    monkeypatch.setattr(angel.provider, "get_market_data", fake)
    f = client.get("/api/derivatives/NIFTY/expiries", headers=auth).json()["futures"][0]
    assert f["oi"] == 31912400 and f["change"] == "50.0" and f["prev_close"] == "26000.0" and f["expiry"] == "2099-12-30"
