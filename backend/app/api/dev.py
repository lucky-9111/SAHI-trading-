"""Developer console API: system health, self-tests, Angel One API, errors, switches, sessions, login attempts, roles, system info and
live logs. Developer role only. Secrets (passwords, keys, tokens) never leave the server."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import audit, health, logbuffer, metrics, permissions as perms, switches
from app.admin.permissions import require
from app.database.session import get_db
from app.models import User
from app.models.admin import LoginAttempt, UserSession

router = APIRouter(prefix="/api/dev", tags=["developer"])
Dev = require("developer")
UTC = dt.timezone.utc


class SwitchIn(BaseModel):
    on: bool


def _iso(t):
    t = health._utc(t)
    return t.isoformat() if t else None


@router.get("/health")
def system_health(_: User = Depends(Dev)):
    return {**health.health(), "selftests": health.selftest_summary()}


@router.post("/selftest")
def run_selftest(user: User = Depends(Dev)):
    s = health.run_selftests()
    audit.record("dev.selftest", user, "", {"passed": s["passed"], "failed": s["failed"]})
    return s


@router.get("/angel")
def angel_api(window: int = 3600, _: User = Depends(Dev)):
    from app.market_data import angel

    window = max(300, min(window, 86400))
    return {**metrics.angel_summary(window), "provider": angel.provider.status(), "configured": angel.AngelProvider.configured()}


@router.post("/angel/probe")
def angel_probe(user: User = Depends(Dev)):
    """One real, read-only call (NIFTY 50 last price) to see whether Angel One answers right now."""
    import time

    from app.market_data import angel
    from app.market_data.provider import ProviderError

    t0 = time.perf_counter()
    try:
        ltp = angel.provider.get_ltp("NSE", "Nifty 50", "99926000")
        out = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "detail": f"NIFTY 50 = {ltp}"}
    except ProviderError as e:
        out = {"ok": False, "ms": round((time.perf_counter() - t0) * 1000), "detail": str(e)}
    audit.record("dev.angel_probe", user, "", {"ok": out["ok"]})
    return out


@router.get("/errors")
def errors(_: User = Depends(Dev)):
    return logbuffer.incidents()


@router.get("/switches")
def get_switches(_: User = Depends(Dev)):
    return switches.all_()


@router.put("/switches/{name}")
def put_switch(name: str, body: SwitchIn, user: User = Depends(Dev)):
    if name not in switches.SWITCHES:
        raise HTTPException(404, "Unknown switch")
    switches.set_(name, body.on)
    audit.record(f"dev.switch.{name}", user, name, {"on": body.on})
    return switches.all_()


@router.get("/sessions")
def sessions(_: User = Depends(Dev), db: Session = Depends(get_db)):
    now = dt.datetime.now(UTC)
    rows = db.execute(select(UserSession, User).join(User, User.id == UserSession.user_id)
                      .where(UserSession.revoked_at.is_(None), UserSession.expires_at > now).order_by(UserSession.last_seen.desc())).all()
    out = []
    for s, u in rows:
        idle = (now - health._utc(s.last_seen)).total_seconds()
        out.append({"id": s.id, "user": u.email, "name": u.name, "role": u.role, "device": s.device, "ip": s.ip,
                    "signed_in": _iso(s.created_at), "last_seen": _iso(s.last_seen), "expires_at": _iso(s.expires_at),
                    "idle_min": int(idle // 60), "state": "online" if idle <= health.ONLINE_S else "gone quiet", "read_only": s.read_only})
    return out


@router.post("/sessions/{sid}/signout")
def end_session(sid: int, user: User = Depends(Dev), db: Session = Depends(get_db)):
    s = db.get(UserSession, sid)
    if not s or s.revoked_at is not None:
        raise HTTPException(404, "Session not found")
    if s.id == user._session_id:
        raise HTTPException(400, "Use Sign out to end your own session")
    s.revoked_at = dt.datetime.now(UTC)
    db.commit()
    audit.record("dev.session_signout", user, f"user:{s.user_id}", {"session": sid})
    return {"ok": True}


@router.get("/logins")
def login_attempts(only_failed: bool = False, _: User = Depends(Dev), db: Session = Depends(get_db)):
    q = select(LoginAttempt).order_by(LoginAttempt.id.desc())
    if only_failed:
        q = q.where(LoginAttempt.success.is_(False))
    hour = dt.datetime.now(UTC) - dt.timedelta(hours=1)
    failed = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.success.is_(False), LoginAttempt.ts >= hour)) or 0
    from app.core.config import get_settings

    s = get_settings()
    return {"failed_last_hour": failed, "policy": f"{s.login_max_failures} wrong attempts lock an email (and an address) for "
                                                  f"{s.login_lock_minutes} minutes. The message never says which part was wrong.",
            "items": [{"ts": _iso(a.ts), "email": a.email, "success": a.success, "reason": a.reason, "ip": a.ip, "device": a.device}
                      for a in db.scalars(q.limit(300))]}


@router.get("/roles")
def roles(_: User = Depends(Dev)):
    return {"roles": list(perms.RANK), "matrix": perms.matrix(), "rules": perms.RULES}


@router.get("/info")
def system_info(_: User = Depends(Dev)):
    return health.info()


@router.get("/logs")
def live_logs(lines: int = 400, level: str = "", _: User = Depends(Dev)):
    rows = logbuffer.tail(lines, level)
    return {"lines": rows, "bytes": sum(len(r) + 1 for r in rows)}
