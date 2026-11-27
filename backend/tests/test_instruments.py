from app.database.session import SessionLocal
from app.market_data.instrument_master import sync_nse_equities

ROWS = [
    {"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "lotsize": "1", "exch_seg": "NSE", "tick_size": "10.000000"},
    {"token": "11536", "symbol": "TCS-EQ", "name": "TCS", "lotsize": "1", "exch_seg": "NSE", "tick_size": "10.000000"},
    {"token": "1594", "symbol": "INFY-EQ", "name": "INFY", "lotsize": "1", "exch_seg": "NSE", "tick_size": "5.000000"},
    {"token": "1", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "lotsize": "1", "exch_seg": "BSE", "tick_size": "5"},
    {"token": "9", "symbol": "NIFTY25JANFUT", "name": "NIFTY", "lotsize": "25", "exch_seg": "NFO", "tick_size": "5"},
]


def seed():
    with SessionLocal() as db:
        return sync_nse_equities(db, ROWS)


def test_sync_only_nse_equities_and_is_idempotent(client, auth):
    assert seed() == 3
    assert seed() == 3
    assert client.get("/api/instruments/status", headers=auth).json()["count"] == 3


def test_search_ranking_and_case(client, auth):
    seed()
    r = client.get("/api/instruments/search", params={"q": "tcs"}, headers=auth).json()
    assert [x["symbol"] for x in r] == ["TCS"]
    r = client.get("/api/instruments/search", params={"q": "I"}, headers=auth).json()
    assert [x["symbol"] for x in r][0] == "INFY"  # prefix beats substring
    assert client.get("/api/instruments/search", params={"q": "zzzz"}, headers=auth).json() == []


def test_search_requires_auth(client):
    assert client.get("/api/instruments/search", params={"q": "tcs"}).status_code == 401
