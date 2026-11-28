"""System health, known-answer self-tests and system info for the developer console. Read-only: nothing here changes data."""
from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
import sys
import time
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

from app.admin import audit, logbuffer, metrics, switches
from app.core.config import get_settings
from app.database.session import SessionLocal
from app.models import AuditLog, User
from app.models.admin import LoginAttempt, UserSession

ONLINE_S = 120          # a page that has not called the API for 2 minutes counts as gone (offline)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _utc(t):
    return t.replace(tzinfo=dt.timezone.utc) if t is not None and t.tzinfo is None else t


def online_user_ids(db) -> set[int]:
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=ONLINE_S)
    return set(db.scalars(select(UserSession.user_id).where(UserSession.revoked_at.is_(None), UserSession.read_only.is_(False),
                                                            UserSession.last_seen >= cut)))


# ------------------------------------------------------------------------------------------------------------------- self-tests
def _checks():
    from app.trading import engine, market_status, notify, pricing
    from app.trading.charges import estimate_charges

    D = Decimal
    yield "charges.intraday_sell", lambda: estimate_charges("INTRADAY", "SELL", D("100000")), D("52.22")
    yield "charges.delivery_buy", lambda: estimate_charges("DELIVERY", "BUY", D("100000")), D("118.62")
    yield "market.weekend_closed", lambda: market_status.status("NSE", dt.datetime(2026, 11, 28, 11, 0, tzinfo=IST)).state, "WEEKEND"
    yield "market.session_open", lambda: market_status.status("NSE", dt.datetime(2026, 11, 27, 10, 0, tzinfo=IST)).is_open, True
    yield "market.pre_open", lambda: market_status.status("NSE", dt.datetime(2026, 11, 27, 9, 5, tzinfo=IST)).state, "PRE_OPEN"
    yield "engine.depth_vwap", lambda: engine._match("BUY", 50, D("1000"), None, (), ((D("1000"), 30), (D("1000.5"), 20))), (50, D("1000.20"))
    yield "engine.limit_never_worse", lambda: engine._match("BUY", 10, D("990"), D("990"), (), ((D("991"), 100),)), (0, None)
    yield "engine.slippage_adverse", lambda: (engine.slip("BUY", D("100"), D("1")), engine.slip("SELL", D("100"), D("1"))), (D("101.00"), D("99.00"))
    yield "pricing.trade_time_ist", lambda: pricing.trade_time({"exchTradeTime": "27-Nov-2026 09:29:58"}).isoformat(), "2026-11-27T03:59:58+00:00"
    yield "notify.indian_grouping", lambda: notify.money(D("1234567.8")), "₹12,34,567.80"
    yield "logs.secrets_masked", lambda: logbuffer.mask('password=hunter2 Authorization: Bearer abc.def.ghi'), "password=*** Authorization: Bearer ***"


_last: dict = {"at": None, "results": []}


def run_selftests() -> dict:
    results = []
    for name, fn, expected in _checks():
        t0 = time.perf_counter()
        try:
            actual = fn()
            ok = actual == expected
        except Exception as e:  # noqa: BLE001
            actual, ok = f"{type(e).__name__}: {e}", False
        results.append({"check": name, "passed": ok, "expected": None if ok else str(expected), "actual": None if ok else str(actual),
                        "ms": round((time.perf_counter() - t0) * 1000, 3)})
    _last.update(at=time.time(), results=results)
    return selftest_summary()


def selftest_summary() -> dict:
    if _last["at"] is None:
        run_selftests()
    r = _last["results"]
    return {"passed": sum(x["passed"] for x in r), "failed": sum(not x["passed"] for x in r), "results": r,
            "last_run_ago_s": round(time.time() - _last["at"])}


# ------------------------------------------------------------------------------------------------------------------- health
def _db_path() -> Path | None:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        return None
    p = Path(url.split(":///", 1)[-1])
    return p if p.is_absolute() else (Path.cwd() / p)


def health() -> dict:
    from app.live import runtime
    from app.market_data import angel
    from app.trading import market_status

    checks: list[dict] = []

    def add(key, title, status, detail):
        checks.append({"key": key, "title": title, "status": status, "detail": detail})

    h = metrics.http_summary(300)
    add("api", "API server", "ok" if h["error_pct"] < 2 else "warn" if h["error_pct"] < 20 else "fail",
        f"{h['requests']} requests in 5 min, {h['error_pct']}% server errors" + (f", p95 {h['p95_ms']} ms" if h["p95_ms"] else ""))

    with SessionLocal() as db:
        t0 = time.perf_counter()
        try:
            db.execute(text("SELECT 1"))
            ms = (time.perf_counter() - t0) * 1000
            p = _db_path()
            free = shutil.disk_usage(p.parent if p else Path.cwd()).free / 1e9
            add("database", "Database", "ok" if ms < 200 else "warn", f"query {ms:.1f} ms, disk free {free:.1f} GB")
        except Exception as e:  # noqa: BLE001
            add("database", "Database", "fail", f"{type(e).__name__}: {e}")

        pl = runtime.pipeline
        nse_open = market_status.is_open("NSE")
        if pl is None:
            add("feed", "Market feed (WebSocket)", "warn" if get_settings().feed_mode != "off" else "ok",
                "pipeline not running" + (" (FEED_MODE=off)" if get_settings().feed_mode == "off" else ""))
        else:
            fs = pl.feed_status()
            r = pl.receiver
            tokens = len(r._wanted) if r else 0
            age = fs.get("last_tick_age_s")
            st = {"connected": "ok", "replay": "ok", "closed": "ok" if not nse_open else "warn"}.get(fs["state"], "fail" if nse_open else "warn")
            add("feed", "Market feed (WebSocket)", st, f"{fs['state']}, {tokens} tokens" + (f", last tick {age}s ago" if age is not None else "")
                + ("" if nse_open else " (market closed)"))

        a = metrics.angel_summary(3600)
        if not angel.AngelProvider.configured():
            add("angel", "Angel One REST", "fail", "credentials are not set in backend/.env")
        else:
            bad = a["errors"] + a["rate_limited"]
            add("angel", "Angel One REST", "ok" if not bad or bad / max(a["calls"], 1) < 0.05 else "warn",
                f"{a['calls']} calls in the last hour, {a['errors']} errors, {a['rate_limited']} rate limited")

        wa = metrics.beat_age("execution_worker")
        if os.environ.get("DISABLE_ENGINE"):
            add("worker", "Execution worker", "warn", "disabled (DISABLE_ENGINE)")
        else:
            add("worker", "Execution worker", "ok" if wa is not None and wa < 30 else "fail",
                f"last pass {wa:.0f}s ago" if wa is not None else "has not run since the start")
        sw = {s["name"]: s["on"] for s in switches.all_()}
        add("switches", "Trading switches", "ok" if sw["orders_enabled"] and sw["engine_enabled"] else "warn",
            ("new orders ON" if sw["orders_enabled"] else "new orders PAUSED") + " · " + ("engine ON" if sw["engine_enabled"] else "engine PAUSED"))

        hour = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        failed = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.success.is_(False), LoginAttempt.ts >= hour)) or 0
        active = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
        add("users", "Users and sessions", "ok" if failed < 20 else "warn",
            f"{len(online_user_ids(db))} online, {active} active users, {failed} failed sign-ins in the last hour")
        intact, rows, broken = audit.verify(db)
        add("audit", "Audit log", "ok" if intact else "fail", f"hash chain intact ({rows} rows)" if intact else f"chain broken at row {broken}")

    s = selftest_summary()
    add("selftest", "Known-answer self-tests", "ok" if not s["failed"] else "fail", f"{s['passed']} passed, {s['failed']} failed")
    inc = logbuffer.incidents()["last_hour"]
    add("incidents", "Incidents (last hour)", "ok" if inc == 0 else "warn" if inc < 20 else "fail", f"{inc} warning(s) / error(s) in the last hour")
    overall = "fail" if any(c["status"] == "fail" for c in checks) else "warn" if any(c["status"] == "warn" for c in checks) else "ok"
    return {"status": overall, "checks": checks, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}


# ------------------------------------------------------------------------------------------------------------------- system info
def info() -> dict:
    import fastapi
    import sqlalchemy

    s = get_settings()
    root = Path(__file__).resolve().parents[3]
    rev = next((p.read_text().strip()[:40] for p in (root / "REVISION", root / "backend" / "REVISION") if p.exists()), None)
    with SessionLocal() as db:
        users = db.scalar(select(func.count()).select_from(User)) or 0
        now = dt.datetime.now(dt.timezone.utc)
        sessions = db.scalar(select(func.count()).select_from(UserSession).where(UserSession.revoked_at.is_(None), UserSession.expires_at > now)) or 0
        audit_rows = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    p = _db_path()
    files, backups = [], []
    if p and p.exists():
        for f in sorted(p.parent.glob(p.name + "*")):
            files.append({"file": f.name, "mb": round(f.stat().st_size / 1e6, 2)})
        for d in {p.parent, p.parent.parent}:
            for f in d.glob("backup-*.db"):
                backups.append({"file": str(f.relative_to(p.parent.parent)), "mb": round(f.stat().st_size / 1e6, 2),
                                "at": dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc).isoformat()})
    backups.sort(key=lambda b: b["at"], reverse=True)
    from app.market_data.angel import AngelProvider

    checks = [
        {"name": "SECRET_KEY", "ok": len(s.secret_key) >= 32 and s.secret_key not in ("CHANGE_ME_IN_ENV",),
         "detail": "signs every sign-in token; use a random string of 32+ characters" if len(s.secret_key) < 32 else "long enough"},
        {"name": "ENVIRONMENT", "ok": s.is_production, "detail": "production turns on the strict start-up checks" if not s.is_production else "production"},
        {"name": "Angel One credentials", "ok": AngelProvider.configured(), "detail": "needed for live data"},
        {"name": "CORS_ORIGINS", "ok": "*" not in s.cors_list, "detail": ", ".join(s.cors_list) or "-"},
        {"name": "TRUSTED_HOSTS", "ok": s.trusted_host_list != ["*"], "detail": ", ".join(s.trusted_host_list)},
        {"name": "Backups", "ok": bool(backups), "detail": f"{len(backups)} backup file(s) next to the database" if backups else "no backup-*.db found"},
    ]
    return {"uptime_s": round(metrics.uptime_s()), "python": platform.python_version(), "fastapi": fastapi.__version__,
            "sqlalchemy": sqlalchemy.__version__, "revision": rev, "environment": s.environment, "feed_mode": s.feed_mode,
            "users": users, "sessions_active": sessions, "audit_rows": audit_rows, "incidents": sum(g["count"] for g in logbuffer.incidents()["grouped"]),
            "platform": platform.platform(), "executable": sys.executable.split(os.sep)[-1], "database": str(p) if p else s.database_url.split("://")[0],
            "files": files, "backups": backups[:10], "checks": checks}
