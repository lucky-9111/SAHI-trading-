from decimal import Decimal

import pytest

from app.api.market import trend_label
from app.database.session import SessionLocal
from app.market_data import angel
from app.market_data.instrument_master import sync_nse_equities
from app.trading import pricing
from tests.conftest import register
from tests.test_instruments import ROWS

FEED = {
    "99926000": {"exchange": "NSE", "symbolToken": "99926000", "ltp": 25884.5, "close": 25819.25, "netChange": 65.25,
                 "percentChange": 0.25, "tradeVolume": 0},
    "2885": {"exchange": "NSE", "symbolToken": "2885", "ltp": 1396.2, "close": 1373.9, "netChange": 22.3,
             "percentChange": 1.62, "tradeVolume": 20028816},
    "11536": {"exchange": "NSE", "symbolToken": "11536", "ltp": 2640.3, "close": 2517.3, "netChange": 123.0,
              "percentChange": 4.89, "tradeVolume": 5534593},
}


@pytest.fixture()
def feed(monkeypatch):
    pricing._qcache.clear()
    calls = {"n": 0}

    def fake(exchange_tokens):
        calls["n"] += 1
        return [FEED[t] for toks in exchange_tokens.values() for t in toks if t in FEED]

    monkeypatch.setattr(angel.provider, "get_market_data", fake)
    return calls


@pytest.fixture()
def seeded(client):
    with SessionLocal() as db:
        sync_nse_equities(db, ROWS + [
            {"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "lotsize": "1", "exch_seg": "NSE", "tick_size": "5"}])


def test_trend_labels():
    assert trend_label(2.0) == "Strong uptrend" and trend_label(0.3) == "Uptrend"
    assert trend_label(0.0) == "Sideways" and trend_label(-0.3) == "Downtrend" and trend_label(-2) == "Strong downtrend"


def test_overview_returns_real_provider_numbers(client, auth, feed):
    d = client.get("/api/market/overview", headers=auth).json()
    nifty = d["indices"][0]
    assert nifty["name"] == "NIFTY 50" and Decimal(nifty["ltp"]) == Decimal("25884.5")
    assert Decimal(nifty["change"]) == Decimal("65.25") and nifty["trend"] == "Uptrend"
    assert [i["key"] for i in d["indices"]] == ["NIFTY50"]  # only what the provider returned


def test_quotes_are_cached_to_protect_rate_limit(client, auth, feed):
    client.get("/api/market/overview", headers=auth)
    client.get("/api/market/overview", headers=auth)
    assert feed["n"] == 2  # one NSE batch + one BSE batch; the second request is served from cache


def test_overview_503_when_provider_down(client, auth, monkeypatch):
    pricing._qcache.clear()
    monkeypatch.setattr(angel.AngelProvider, "configured", staticmethod(lambda: False))
    r = client.get("/api/market/overview", headers=auth)
    assert r.status_code == 503 and "credentials" in r.json()["detail"]


def test_stock_list_skips_unknown_symbols(client, auth, feed, seeded):
    d = client.get("/api/market/lists/popular", headers=auth).json()
    syms = [r["symbol"] for r in d["items"]]
    assert "RELIANCE" in syms and "TCS" in syms and "SBIN" not in syms
    assert client.get("/api/market/lists/nope", headers=auth).status_code == 404


def test_watchlist_crud_and_quotes(client, auth, feed, seeded):
    lists = client.get("/api/watchlists", headers=auth).json()
    assert len(lists) == 1 and lists[0]["items"] == []
    wid = lists[0]["id"]
    assert client.post(f"/api/watchlists/{wid}/items", json={"symbol": "reliance"}, headers=auth).status_code == 201
    assert client.post(f"/api/watchlists/{wid}/items", json={"symbol": "RELIANCE"}, headers=auth).status_code == 409
    assert client.post(f"/api/watchlists/{wid}/items", json={"symbol": "NOPE"}, headers=auth).status_code == 404
    item = client.get("/api/watchlists", headers=auth).json()[0]["items"][0]
    assert item["symbol"] == "RELIANCE" and Decimal(item["ltp"]) == Decimal("1396.2") and item["pct"] == "1.62"
    assert client.delete(f"/api/watchlists/{wid}/items/{item['instrument_id']}", headers=auth).status_code == 204
    assert client.get("/api/watchlists", headers=auth).json()[0]["items"] == []


def test_multiple_watchlists_and_separation(client, auth, seeded):
    assert client.post("/api/watchlists", json={"name": "Swing"}, headers=auth).status_code == 201
    assert client.post("/api/watchlists", json={"name": "Swing"}, headers=auth).status_code == 409
    wid = client.get("/api/watchlists", headers=auth).json()[0]["id"]
    h2 = register(client, "w2@example.com")
    assert client.post(f"/api/watchlists/{wid}/items", json={"symbol": "TCS"}, headers=h2).status_code == 404
    assert client.delete(f"/api/watchlists/{wid}", headers=h2).status_code == 404
    assert client.delete(f"/api/watchlists/{wid}", headers=auth).status_code == 204


def test_watchlist_without_prices_still_lists_stocks(client, auth, seeded, monkeypatch):
    pricing._qcache.clear()
    monkeypatch.setattr(angel.AngelProvider, "configured", staticmethod(lambda: False))
    wid = client.get("/api/watchlists", headers=auth).json()[0]["id"]
    client.post(f"/api/watchlists/{wid}/items", json={"symbol": "TCS"}, headers=auth)
    w = client.get("/api/watchlists", headers=auth).json()[0]
    assert w["prices_available"] is False and w["items"][0]["ltp"] is None
