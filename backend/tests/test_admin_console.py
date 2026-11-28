"""Admin console and developer console: roles, sessions, sign-in protection, audit log, switches, view-as, calendar, health."""
import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.admin import logbuffer
from app.database.session import SessionLocal, engine as db_engine
from app.models import User
from app.trading import market_status as ms
from tests.conftest import register
from tests.test_trading import acct, order, px  # noqa: F401

D = Decimal


def login(client, email, password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def team(client):
    """owner (first account = developer + owner), an admin and a user."""
    owner = register(client, "owner@example.com", "Owner")
    user = register(client, "user@example.com", "User")
    admin = register(client, "admin@example.com", "Admin")
    with SessionLocal() as db:
        ids = {u.email: u.id for u in db.query(User)}
    client.patch(f"/api/admin/users/{ids['admin@example.com']}", json={"role": "admin"}, headers=owner)
    return {"owner": owner, "admin": admin, "user": user, "ids": ids}


# ---------------------------------------------------------------------------------------------------------------- roles
def test_first_account_owns_the_installation(client):
    h = register(client, "first@example.com")
    me = client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "developer" and me["is_owner"] is True
    h2 = register(client, "second@example.com")
    assert client.get("/api/auth/me", headers=h2).json()["role"] == "user"


def test_console_access_by_role(client, team):
    assert client.get("/api/admin/overview", headers=team["user"]).status_code == 403
    assert client.get("/api/admin/overview", headers=team["admin"]).status_code == 200
    assert client.get("/api/dev/health", headers=team["admin"]).status_code == 403
    assert client.get("/api/dev/health", headers=team["owner"]).status_code == 200
    assert client.get("/api/admin/users").status_code == 401


def test_who_may_create_and_manage_whom(client, team):
    ids = team["ids"]
    assert client.post("/api/admin/users", json={"name": "A2", "email": "a2@example.com", "role": "admin"}, headers=team["admin"]).status_code == 403
    r = client.post("/api/admin/users", json={"name": "New", "email": "new@example.com"}, headers=team["admin"])
    assert r.status_code == 201 and len(r.json()["temporary_password"]) >= 10
    assert login(client, "new@example.com", r.json()["temporary_password"]).status_code == 200
    assert client.patch(f"/api/admin/users/{ids['owner@example.com']}", json={"is_active": False}, headers=team["admin"]).status_code == 403
    assert client.patch(f"/api/admin/users/{ids['owner@example.com']}", json={"is_active": False}, headers=team["owner"]).status_code == 403  # self
    assert client.delete(f"/api/admin/users/{ids['admin@example.com']}", headers=team["admin"]).status_code == 403                        # self
    assert client.post("/api/admin/users", json={"name": "D", "email": "d@example.com", "role": "developer"}, headers=team["owner"]).status_code == 201


def test_disable_ends_sessions_and_blocks_sign_in(client, team):
    uid = team["ids"]["user@example.com"]
    assert client.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=team["admin"]).status_code == 200
    assert client.get("/api/auth/me", headers=team["user"]).status_code == 401           # the open session ended at once
    assert login(client, "user@example.com").status_code == 403
    client.patch(f"/api/admin/users/{uid}", json={"is_active": True}, headers=team["admin"])
    assert login(client, "user@example.com").status_code == 200


def test_remove_user_takes_their_portfolios(client, team):
    uid = team["ids"]["user@example.com"]
    client.post("/api/accounts", json={"name": "P", "initial_capital": "1000"}, headers=team["user"])
    assert client.delete(f"/api/admin/users/{uid}", headers=team["admin"]).status_code == 200
    assert all(u["id"] != uid for u in client.get("/api/admin/users", headers=team["admin"]).json()["users"])


# ---------------------------------------------------------------------------------------------------------------- sessions / sign-in
def test_logout_and_admin_signout_end_sessions(client, team):
    t = login(client, "user@example.com").json()["access_token"]
    assert client.post("/api/auth/logout", headers=hdr(t)).status_code == 200
    assert client.get("/api/auth/me", headers=hdr(t)).status_code == 401
    r = client.post(f"/api/admin/users/{team['ids']['user@example.com']}/signout", headers=team["admin"]).json()
    assert r["sessions_ended"] >= 1 and client.get("/api/auth/me", headers=team["user"]).status_code == 401
    sess = client.get("/api/dev/sessions", headers=team["owner"]).json()
    assert {s["user"] for s in sess} == {"owner@example.com", "admin@example.com"}


def test_five_wrong_passwords_lock_the_email(client, team):
    for _ in range(5):
        assert login(client, "user@example.com", "wrong-password").status_code == 401
    r = login(client, "user@example.com")                                               # even the right password is refused now
    assert r.status_code == 429 and "Try again in" in r.json()["detail"]
    lg = client.get("/api/dev/logins?only_failed=true", headers=team["owner"]).json()
    assert lg["failed_last_hour"] >= 6 and {i["reason"] for i in lg["items"]} == {"bad_credentials", "locked"}


def test_change_password_signs_out_other_devices(client, team):
    other = login(client, "user@example.com").json()["access_token"]
    r = client.post("/api/auth/change-password", json={"current_password": "password123", "new_password": "newpassword1"}, headers=team["user"])
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=hdr(other)).status_code == 401 and client.get("/api/auth/me", headers=team["user"]).status_code == 200
    assert login(client, "user@example.com", "newpassword1").status_code == 200


def test_signup_switch(client, team):
    client.put("/api/dev/switches/signup_enabled", json={"on": False}, headers=team["owner"])
    r = client.post("/api/auth/register", json={"email": "x@example.com", "name": "X", "password": "password123"})
    assert r.status_code == 403 and "closed" in r.json()["detail"]


# ---------------------------------------------------------------------------------------------------------------- view as
def test_view_as_is_read_only(client, team):
    uid = team["ids"]["user@example.com"]
    acc = client.post("/api/accounts", json={"name": "Main", "initial_capital": "1000"}, headers=team["user"]).json()["id"]
    v = client.post(f"/api/admin/users/{uid}/view-as", headers=team["admin"]).json()
    me = client.get("/api/auth/me", headers=hdr(v["token"])).json()
    assert me["email"] == "user@example.com" and me["read_only"] is True
    assert [a["id"] for a in client.get("/api/accounts", headers=hdr(v["token"])).json()] == [acc]
    r = client.post(f"/api/accounts/{acc}/deposit", json={"amount": "5"}, headers=hdr(v["token"]))
    assert r.status_code == 403 and "Read-only" in r.json()["detail"]
    assert client.get("/api/admin/overview", headers=hdr(v["token"])).status_code == 403
    assert client.post(f"/api/admin/users/{team['ids']['admin@example.com']}/view-as", headers=team["admin"]).status_code == 403   # self


# ---------------------------------------------------------------------------------------------------------------- audit log
def test_audit_log_is_hash_chained_and_append_only(client, team):
    a = client.get("/api/admin/audit", headers=team["admin"]).json()
    actions = [i["action"] for i in a["items"]]
    assert a["intact"] and "user.role" in actions and "user.register" in actions and "login.success" not in actions
    with pytest.raises(DatabaseError, match="append-only"):
        with db_engine.begin() as c:
            c.execute(text("UPDATE audit_log SET action = 'x'"))
    with pytest.raises(DatabaseError, match="append-only"):
        with db_engine.begin() as c:
            c.execute(text("DELETE FROM audit_log"))
    assert client.get("/api/admin/audit?q=user.role", headers=team["admin"]).json()["items"][0]["detail"] == {"role": ["user", "admin"]}


# ---------------------------------------------------------------------------------------------------------------- switches
def test_order_and_engine_switches(client, auth, acct, px):  # noqa: F811
    assert order(client, auth, acct, quantity=1).json()["status"] == "FILLED"                      # auth = first account = owner
    client.put("/api/dev/switches/orders_enabled", json={"on": False}, headers=auth)
    r = order(client, auth, acct, quantity=1)
    assert r.status_code == 400 and "paused by the administrator" in r.json()["detail"]
    pid = client.get(f"/api/accounts/{acct}/positions", headers=auth).json()[0]["id"]
    assert client.post(f"/api/accounts/{acct}/positions/{pid}/exit", json={}, headers=auth).json()["order"]["status"] == "FILLED"  # exits still work
    client.put("/api/dev/switches/orders_enabled", json={"on": True}, headers=auth)
    lim = order(client, auth, acct, order_type="LIMIT", limit_price="990", quantity=1).json()
    client.put("/api/dev/switches/engine_enabled", json={"on": False}, headers=auth)
    from app.trading import engine
    with SessionLocal() as db:
        iid = db.scalar(engine.select(engine.Instrument.id).where(engine.Instrument.symbol == "RELIANCE"))
        assert engine.process_price(db, iid, D("980")) == []                                       # paused: no fill
    client.put("/api/dev/switches/engine_enabled", json={"on": True}, headers=auth)
    with SessionLocal() as db:
        assert engine.process_price(db, iid, D("980")) == [f"order {lim['id']} FILLED"]
    assert [a["action"] for a in client.get("/api/admin/audit?q=dev.switch", headers=auth).json()["items"]][:2] == [
        "dev.switch.engine_enabled", "dev.switch.engine_enabled"]


# ---------------------------------------------------------------------------------------------------------------- calendar + announcements
def test_calendar_from_the_console_changes_market_status(client, team):
    r = client.post("/api/admin/calendar", json={"date": "2026-11-27", "exchange": "NSE", "kind": "holiday", "note": "Test holiday"},
                    headers=team["admin"])
    assert r.status_code == 201
    assert ms.status("NSE").state == "HOLIDAY"                                                     # engine clock: Fri 27 Nov 09:30
    assert client.delete("/api/admin/calendar/2026-11-27/NSE", headers=team["admin"]).status_code == 200
    assert ms.status("NSE").is_open
    bad = client.post("/api/admin/calendar", json={"date": "2026-11-29", "exchange": "NSE", "kind": "special", "start": "19:00", "end": "18:00"},
                      headers=team["admin"])
    assert bad.status_code == 400


def test_calendar_nse_sync_parser(client):
    from app.live import calendar
    with SessionLocal() as db:
        n = calendar.sync_nse(db, fetch=lambda: {"FO": [{"tradingDate": "25-Dec-2026", "description": "Christmas"}, {"tradingDate": "bad"}]})
    assert n == 1 and ms.status("NSE", dt.datetime(2026, 12, 25, 10, 0, tzinfo=ms.IST)).state == "HOLIDAY"


def test_announcements_reach_every_user(client, team):
    a = client.post("/api/admin/announcements", json={"title": "Monday is a holiday", "level": "warning"}, headers=team["admin"]).json()
    assert [x["title"] for x in client.get("/api/announcements", headers=team["user"]).json()] == ["Monday is a holiday"]
    client.put(f"/api/admin/announcements/{a['id']}", json={"title": "Monday is a holiday", "active": False}, headers=team["admin"])
    assert client.get("/api/announcements", headers=team["user"]).json() == []
    assert client.post("/api/admin/announcements", json={"title": "x"}, headers=team["user"]).status_code == 403


# ---------------------------------------------------------------------------------------------------------------- developer console
def test_health_selftests_info_roles_logs(client, team):
    h = client.get("/api/dev/health", headers=team["owner"]).json()
    keys = {c["key"] for c in h["checks"]}
    assert {"api", "database", "feed", "angel", "worker", "users", "audit", "selftest", "switches"} <= keys
    assert h["selftests"]["failed"] == 0, h["selftests"]
    assert next(c for c in h["checks"] if c["key"] == "audit")["status"] == "ok"
    s = client.post("/api/dev/selftest", headers=team["owner"]).json()
    assert s["passed"] >= 10 and s["failed"] == 0
    info = client.get("/api/dev/info", headers=team["owner"]).json()
    assert info["users"] == 3 and any(c["name"] == "SECRET_KEY" for c in info["checks"])
    roles = client.get("/api/dev/roles", headers=team["owner"]).json()
    row = next(r for r in roles["matrix"] if r["permission"] == "system.manage")
    assert row == {"permission": "system.manage", "user": False, "admin": False, "developer": True}
    import logging
    logging.getLogger("app.test").error("broker said password=hunter2 token=abc123")
    logs = client.get("/api/dev/logs?lines=50", headers=team["owner"]).json()["lines"]
    assert any("password=***" in line and "hunter2" not in line for line in logs)
    errs = client.get("/api/dev/errors", headers=team["owner"]).json()
    assert any(g["component"] == "app.test" for g in errs["grouped"])
    logbuffer.reset()


def test_angel_calls_are_measured(client, team, monkeypatch):
    from app.market_data import angel
    from app.market_data.provider import ProviderError

    p = angel.AngelProvider(client_factory=None)
    monkeypatch.setattr(p, "_request_once", lambda call: {"status": True, "data": {"ltp": 101.5}})
    assert p.get_ltp("NSE", "X", "1") == D("101.5")

    def boom(call):
        raise ProviderError("down")
    monkeypatch.setattr(p, "_request_once", boom)
    with pytest.raises(ProviderError):
        p.get_ltp("NSE", "X", "1")
    a = client.get("/api/dev/angel", headers=team["owner"]).json()
    ltp = next(e for e in a["endpoints"] if e["endpoint"] == "ltp")
    assert ltp["count"] >= 2 and ltp["errors"] >= 1 and ltp["last_error"] == "down"


def test_overview_counts(client, team):
    o = client.get("/api/admin/overview", headers=team["admin"]).json()
    assert o["stats"]["active"] == 3 and o["stats"]["online"] == 3 and len(o["signins"]) == 30
    u = client.get("/api/admin/users", headers=team["admin"]).json()
    me = next(x for x in u["users"] if x["email"] == "admin@example.com")
    assert me["can_manage"] is False and u["assignable_roles"] == ["user"]
