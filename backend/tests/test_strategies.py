from decimal import Decimal

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import Strategy
from app.services.accounts import DEFAULT_STRATEGIES
from tests.conftest import register
from tests.test_trading import acct, balance, order, positions, px  # noqa: F401

D = Decimal
NAMES = ["Manual", "System 1", "GFS", "Advance GFS", "50 GFS", "PRD", "NRD", "CUP Pattern", "Top Bottom"]


def strategies(client, auth):
    return {s["name"]: s["id"] for s in client.get("/api/strategies", headers=auth).json()}


def test_default_strategies_are_seeded_for_new_users(client, auth):
    assert list(strategies(client, auth)) == NAMES == DEFAULT_STRATEGIES


def test_missing_defaults_added_for_existing_users_without_duplicates(client, auth):
    with SessionLocal() as db:
        for s in db.scalars(select(Strategy).where(Strategy.name.in_(["GFS", "PRD"]))).all():
            db.delete(s)
        db.add(Strategy(user_id=1, name="My Own", description="custom"))
        db.commit()
    got = strategies(client, auth)
    assert {"GFS", "PRD", "My Own"} <= set(got) and len(got) == len(NAMES) + 1  # restored, custom kept
    assert len(strategies(client, auth)) == len(NAMES) + 1  # idempotent


def test_strategy_lists_are_per_user(client, auth):
    h2 = register(client, "s2@example.com")
    assert set(strategies(client, auth).values()).isdisjoint(set(strategies(client, h2).values()))


def test_strategy_travels_with_order_position_and_trade(client, auth, acct, px):  # noqa: F811
    gfs = strategies(client, auth)["GFS"]
    o = order(client, auth, acct, strategy_id=gfs, stop_loss="950", target="1100").json()
    assert o["strategy"] == "GFS"
    p = positions(client, auth, acct)[0]
    assert p["strategy"] == "GFS"
    px["price"] = D("1010")
    t = client.post(f"/api/accounts/{acct}/positions/{p['id']}/exit", json={}, headers=auth).json()["trade"]
    assert t["strategy"] == "GFS"
    assert client.get(f"/api/accounts/{acct}/orders", headers=auth).json()[0]["strategy"] == "GFS"


def test_order_without_strategy_is_manual(client, auth, acct, px):  # noqa: F811
    assert order(client, auth, acct).json()["strategy"] == "Manual"
    assert positions(client, auth, acct)[0]["strategy"] == "Manual"


def test_other_users_strategy_is_rejected(client, auth, acct, px):  # noqa: F811
    h2 = register(client, "s3@example.com")
    foreign = strategies(client, h2)["GFS"]
    r = order(client, auth, acct, strategy_id=foreign)
    assert r.status_code == 400 and "strategy" in r.json()["detail"].lower()
    assert positions(client, auth, acct) == []


def test_symbol_context_shows_strategy_for_open_position_orders_and_trades(client, auth, acct, px):  # noqa: F811
    s = strategies(client, auth)
    order(client, auth, acct, strategy_id=s["System 1"], stop_loss="950", target="1100")
    order(client, auth, acct, order_type="LIMIT", limit_price="900", strategy_id=s["PRD"], symbol="TCS")
    px["price"] = D("1010")
    ctx = client.get(f"/api/accounts/{acct}/symbol-context", params={"symbol": "reliance"}, headers=auth).json()
    assert [p["strategy"] for p in ctx["positions"]] == ["System 1"]
    assert ctx["positions"][0]["stop_loss"] == "950.00" and ctx["trades"] == []
    pid = ctx["positions"][0]["id"]
    client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth)
    ctx = client.get(f"/api/accounts/{acct}/symbol-context", params={"symbol": "RELIANCE"}, headers=auth).json()
    assert ctx["positions"] == [] and ctx["trades"][0]["strategy"] == "System 1"
    tcs = client.get(f"/api/accounts/{acct}/symbol-context", params={"symbol": "TCS"}, headers=auth).json()
    assert tcs["orders"][0]["strategy"] == "PRD" and tcs["positions"] == []
    assert client.get(f"/api/accounts/{acct}/symbol-context", params={"symbol": "NOPE"}, headers=auth).json() == {
        "positions": [], "orders": [], "trades": []}


def test_symbol_context_is_private_to_the_account_owner(client, auth, acct, px):  # noqa: F811
    order(client, auth, acct)
    h2 = register(client, "s4@example.com")
    assert client.get(f"/api/accounts/{acct}/symbol-context", params={"symbol": "RELIANCE"}, headers=h2).status_code == 404
