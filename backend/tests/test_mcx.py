from datetime import date, datetime
from decimal import Decimal

from app.market_data import instrument_master as im
from app.models.market import Instrument
from app.trading import pricing
from app.trading.charges import estimate_charges
from tests.conftest import register

ROWS = [
    {"exch_seg": "MCX", "instrumenttype": "FUTCOM", "name": "GOLD", "symbol": "GOLD04JUN27FUT", "token": "575691", "expiry": "04JUN2027", "lotsize": "1", "tick_size": "100"},
    {"exch_seg": "MCX", "instrumenttype": "FUTCOM", "name": "GOLDM", "symbol": "GOLDM04DEC26FUT", "token": "575011", "expiry": "04DEC2026", "lotsize": "100", "tick_size": "100"},
    {"exch_seg": "MCX", "instrumenttype": "FUTCOM", "name": "CRUDEOIL", "symbol": "CRUDEOIL21JUN27FUT", "token": "584774", "expiry": "21JUN2027", "lotsize": "100", "tick_size": "100"},
    {"exch_seg": "MCX", "instrumenttype": "FUTCOM", "name": "KAPAS", "symbol": "KAPAS30NOV26FUT", "token": "1", "expiry": "30NOV2026", "lotsize": "4", "tick_size": "50"},   # not listed
    {"exch_seg": "MCX", "instrumenttype": "FUTCOM", "name": "ZINC", "symbol": "ZINC30OCT25FUT", "token": "2", "expiry": "30OCT2025", "lotsize": "5", "tick_size": "5"},        # expired
]


def test_sync_mcx_units_and_filters():
    from app.database.session import SessionLocal, Base, engine
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as db:
        assert im.sync_mcx(db, ROWS, today=date(2026, 11, 27)) == 3
        lots = {i.underlying: i.lot_size for i in db.query(Instrument).filter(Instrument.exchange == "MCX")}
        assert lots == {"GOLD": 100, "GOLDM": 10, "CRUDEOIL": 100}      # GOLD per-10g units, not the 1 kg contract lot


def test_mcx_hours_and_charges():
    ist = pricing.IST
    night = datetime(2026, 11, 27, 21, 0, tzinfo=ist)       # Friday 21:00
    assert pricing.is_market_open(night, "MCX") and not pricing.is_market_open(night, "NSE")
    assert not pricing.is_market_open(datetime(2026, 11, 28, 12, 0, tzinfo=ist), "MCX")   # Saturday
    assert pricing.session_close(night, "MCX").hour == 23
    sell = estimate_charges("NRML", "SELL", Decimal(1000000), "FUT", "MCX")
    nse = estimate_charges("NRML", "SELL", Decimal(1000000), "FUT", "NFO")
    assert sell > 0 and sell != nse


def test_commodities_and_fno_endpoints(client, monkeypatch):
    from app.database.session import SessionLocal
    h = register(client)
    with SessionLocal() as db:
        im.sync_mcx(db, ROWS, today=date(2026, 11, 27)); db.commit()
    monkeypatch.setattr(pricing, "get_quotes", lambda specs, ttl=10: {})
    r = client.get("/api/market/commodities", headers=h)
    assert r.status_code == 200
    names = [x["symbol"] for x in r.json()["items"]]
    assert names[:3] == ["GOLD", "GOLDM", "CRUDEOIL"] and r.json()["items"][0]["exchange"] == "MCX"
    assert client.get("/api/market/fno", headers=h).status_code == 200
    ex = client.get("/api/derivatives/GOLD/expiries", headers=h).json()
    assert ex["chart_exchange"] == "MCX" and ex["futures"][0]["exchange"] == "MCX"
    assert any(x["symbol"] == "GOLD" and x["exchange"] == "MCX" for x in client.get("/api/instruments/search?q=gol", headers=h).json())


def test_live_ticks_endpoint(client):
    from app.market_data.live_feed import feed
    h = register(client)
    feed._on_tick({"exchange_type": 5, "token": '"575691"', "last_traded_price": 12511400, "exchange_timestamp": 1790000000000})
    feed._on_tick({"exchange_type": 1, "token": "2885", "last_traded_price": 139450, "exchange_timestamp": 1790000000000})
    r = client.get("/api/market/ticks?s=MCX:575691,NSE:2885,NSE:1", headers=h).json()
    assert r["ticks"]["MCX:575691"]["ltp"] == 125114.0 and r["ticks"]["NSE:2885"]["ltp"] == 1394.5
    assert "NSE:1" not in r["ticks"] and r["feed"]["connected"] is False
