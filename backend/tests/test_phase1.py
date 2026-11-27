from decimal import Decimal

from tests.conftest import register


def mk_account(client, auth, name="Main", capital="1000000"):
    r = client.post("/api/accounts", json={"name": name, "initial_capital": capital}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def test_register_login_and_me(client):
    h = register(client)
    assert client.get("/api/auth/me", headers=h).json()["email"] == "a@example.com"
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "password123"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}).status_code == 401


def test_duplicate_email_rejected(client):
    register(client)
    r = client.post("/api/auth/register", json={"email": "A@example.com", "name": "x", "password": "password123"})
    assert r.status_code == 409


def test_requires_auth(client):
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/accounts", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_create_account_with_ten_lakh(client, auth):
    acc = mk_account(client, auth)
    assert Decimal(acc["balance"]) == Decimal("1000000.00")
    led = client.get(f"/api/accounts/{acc['id']}/ledger", headers=auth).json()
    assert len(led) == 1 and led[0]["entry_type"] == "INITIAL"


def test_deposit_and_withdraw_update_ledger(client, auth):
    acc = mk_account(client, auth)
    base = f"/api/accounts/{acc['id']}"
    assert client.post(f"{base}/deposit", json={"amount": "50000.50"}, headers=auth).status_code == 200
    assert client.post(f"{base}/withdraw", json={"amount": "25000"}, headers=auth).status_code == 200
    accounts = client.get("/api/accounts", headers=auth).json()
    assert Decimal(accounts[0]["balance"]) == Decimal("1025000.50")
    led = client.get(f"{base}/ledger", headers=auth).json()
    assert [e["entry_type"] for e in led] == ["WITHDRAWAL", "DEPOSIT", "INITIAL"]
    assert Decimal(led[0]["balance_after"]) == Decimal("1025000.50")


def test_cannot_overdraw_or_use_bad_amounts(client, auth):
    acc = mk_account(client, auth, capital="1000")
    base = f"/api/accounts/{acc['id']}"
    assert client.post(f"{base}/withdraw", json={"amount": "1000.01"}, headers=auth).status_code == 400
    assert client.post(f"{base}/withdraw", json={"amount": "-5"}, headers=auth).status_code == 422
    assert client.post(f"{base}/deposit", json={"amount": "0"}, headers=auth).status_code == 422
    assert Decimal(client.get("/api/accounts", headers=auth).json()[0]["balance"]) == Decimal("1000.00")


def test_decimal_precision_no_float_drift(client, auth):
    acc = mk_account(client, auth, capital="0.10")
    base = f"/api/accounts/{acc['id']}"
    client.post(f"{base}/deposit", json={"amount": "0.20"}, headers=auth)
    assert Decimal(client.get("/api/accounts", headers=auth).json()[0]["balance"]) == Decimal("0.30")


def test_portfolio_separation_between_users(client):
    h1 = register(client, "u1@example.com")
    h2 = register(client, "u2@example.com")
    acc = mk_account(client, h1)
    base = f"/api/accounts/{acc['id']}"
    assert client.get(f"{base}/dashboard", headers=h2).status_code == 404
    assert client.post(f"{base}/deposit", json={"amount": "10"}, headers=h2).status_code == 404
    assert client.get(f"{base}/ledger", headers=h2).status_code == 404
    assert client.get("/api/accounts", headers=h2).json() == []


def test_multiple_independent_portfolios(client, auth):
    a = mk_account(client, auth, "Swing", "500000")
    b = mk_account(client, auth, "Intraday", "200000")
    client.post(f"/api/accounts/{a['id']}/deposit", json={"amount": "1000"}, headers=auth)
    bal = {x["name"]: Decimal(x["balance"]) for x in client.get("/api/accounts", headers=auth).json()}
    assert bal == {"Swing": Decimal("501000.00"), "Intraday": Decimal("200000.00")}
    r = client.post("/api/accounts", json={"name": "Swing", "initial_capital": "1"}, headers=auth)
    assert r.status_code == 409


def test_dashboard_reads_from_db_and_empty_state(client, auth):
    acc = mk_account(client, auth)
    d = client.get(f"/api/accounts/{acc['id']}/dashboard", headers=auth).json()
    assert Decimal(str(d["capital"]["available_balance"])) == Decimal("1000000.00")
    assert d["has_trades"] is False and d["recent_trades"] == [] and d["stats"]["win_rate"] is None
