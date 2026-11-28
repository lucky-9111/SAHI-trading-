"""Admin console API: overview, users, audit log, announcements, market calendar. Admin role or higher."""
from __future__ import annotations

import datetime as dt
import json
import secrets
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import audit, health, permissions as perms
from app.admin.permissions import require
from app.api.auth import open_session, revoke_sessions
from app.api.deps import current_user
from app.core.security import hash_password
from app.database.session import get_db
from app.live import calendar
from app.models import Announcement, AuditLog, Order, Position, Trade, TradingAccount, User
from app.models.admin import LoginAttempt, UserSession
from app.models.live import MarketCalendarRow
from app.models.market import Instrument
from app.models.trading import WORKING_STATUSES
from app.services.accounts import ensure_default_strategies, get_balance
from app.trading import market_status, pricing

router = APIRouter(prefix="/api/admin", tags=["admin"])
public_router = APIRouter(prefix="/api", tags=["announcements"])
Admin = require("admin")
UTC = dt.timezone.utc


class NewUserIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    role: Literal["user", "admin", "developer"] = "user"


class UserPatchIn(BaseModel):
    role: Literal["user", "admin", "developer"] | None = None
    is_active: bool | None = None


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=2000)
    level: Literal["info", "warning", "success"] = "info"
    active: bool = True


class CalendarIn(BaseModel):
    date: dt.date
    exchange: Literal["NSE", "BSE", "MCX"] = "NSE"
    kind: Literal["holiday", "special", "late_open"]
    start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    note: str = Field(default="", max_length=200)


def _iso(t):
    t = health._utc(t)
    return t.isoformat() if t else None


def _temp_password() -> str:
    return secrets.token_urlsafe(9)


# ------------------------------------------------------------------------------------------------------------------- P&L across users
def _ltps(db: Session, positions: list[Position]) -> dict[int, Decimal]:
    """instrument_id -> latest price for display totals (live tick if fresh, else one batched quote call)."""
    from app.live import runtime

    insts = {i.id: i for i in db.scalars(select(Instrument).where(Instrument.id.in_({p.instrument_id for p in positions})))} if positions else {}
    out, need = {}, []
    for iid, i in insts.items():
        t = runtime.fresh_tick(i.exchange, i.token, max_age=30)
        if t is not None:
            out[iid] = Decimal(str(t.ltp))
        else:
            need.append(i)
    if need:
        try:
            q = pricing.get_quotes([(i.exchange, i.token) for i in need])
            for i in need:
                if (i.exchange, i.token) in q:
                    out[i.id] = q[(i.exchange, i.token)].ltp
        except pricing.PriceUnavailable:
            pass
    return out


def _upnl(p: Position, ltp: Decimal | None) -> Decimal | None:
    if ltp is None:
        return None
    value = ltp * p.quantity
    return (value - p.entry_value) if p.side == "BUY" else (p.entry_value - value)


def _user_rows(db: Session) -> list[dict]:
    users = db.scalars(select(User).order_by(User.id)).all()
    online = health.online_user_ids(db)
    accs = db.scalars(select(TradingAccount)).all()
    acc_user = {a.id: a.user_id for a in accs}
    open_pos = db.scalars(select(Position).where(Position.status == "OPEN")).all()
    ltps = _ltps(db, open_pos)
    realized = dict(db.execute(select(Trade.account_id, func.sum(Trade.net_pnl)).group_by(Trade.account_id)).all())
    last_sess = {}
    for s in db.scalars(select(UserSession).where(UserSession.read_only.is_(False)).order_by(UserSession.last_seen)):
        last_sess[s.user_id] = s
    rows = []
    for u in users:
        mine = [p for p in open_pos if acc_user.get(p.account_id) == u.id]
        up = [_upnl(p, ltps.get(p.instrument_id)) for p in mine]
        ls = last_sess.get(u.id)
        rows.append({
            "id": u.id, "name": u.name, "email": u.email, "role": u.role, "is_owner": bool(u.is_owner), "is_active": bool(u.is_active),
            "online": u.id in online, "device": ls.device if ls else None, "last_seen": _iso(ls.last_seen) if ls else None,
            "created_at": _iso(u.created_at),
            "accounts": sum(1 for a in accs if a.user_id == u.id),
            "balance": str(sum((get_balance(db, a.id) for a in accs if a.user_id == u.id), Decimal(0))),
            "open_positions": len(mine),
            "working_orders": db.scalar(select(func.count()).select_from(Order).join(TradingAccount, TradingAccount.id == Order.account_id)
                                        .where(TradingAccount.user_id == u.id, Order.status.in_(WORKING_STATUSES))) or 0,
            "unrealized": str(sum((x for x in up if x is not None), Decimal(0)).quantize(Decimal("0.01"))) if mine else "0.00",
            "unrealized_partial": any(x is None for x in up),
            "realized": str(Decimal(str(sum((realized.get(a.id) or 0) for a in accs if a.user_id == u.id))).quantize(Decimal("0.01"))),
        })
    return rows


# ------------------------------------------------------------------------------------------------------------------- overview
@router.get("/overview")
def overview(user: User = Depends(Admin), db: Session = Depends(get_db)):
    rows = _user_rows(db)
    now = dt.datetime.now(UTC)
    days = [(now - dt.timedelta(days=i)).astimezone(health.IST).date() for i in range(29, -1, -1)]
    since = dt.datetime.combine(days[0], dt.time(0), tzinfo=health.IST).astimezone(UTC)
    ok_by, bad_by = {d: set() for d in days}, {d: 0 for d in days}
    for a in db.scalars(select(LoginAttempt).where(LoginAttempt.ts >= since)):
        d = health._utc(a.ts).astimezone(health.IST).date()
        if d in ok_by:
            if a.success:
                ok_by[d].add(a.email)
            elif a.reason in ("bad_credentials", "locked"):
                bad_by[d] += 1
    h = health.health()
    attention = [{"title": c["title"], "detail": c["detail"], "status": c["status"]} for c in h["checks"] if c["status"] != "ok"]
    hour = now - dt.timedelta(hours=1)
    for email, n in db.execute(select(LoginAttempt.email, func.count()).where(LoginAttempt.success.is_(False), LoginAttempt.ts >= hour,
                                                                               LoginAttempt.reason == "bad_credentials")
                               .group_by(LoginAttempt.email).having(func.count() >= 3)).all():
        attention.append({"title": "Repeated failed sign-ins", "detail": f"{email}: {n} failed attempts in the last hour", "status": "warn"})
    return {
        "stats": {"online": sum(r["online"] for r in rows), "active": sum(r["is_active"] for r in rows),
                  "disabled": sum(not r["is_active"] for r in rows), "open_positions": sum(r["open_positions"] for r in rows),
                  "working_orders": sum(r["working_orders"] for r in rows),
                  "unrealized": str(sum((Decimal(r["unrealized"]) for r in rows), Decimal(0)))},
        "attention": attention,
        "system": {"status": h["status"], "checks": [c for c in h["checks"] if c["key"] in ("feed", "worker", "users", "incidents", "switches")]},
        "signins": [{"day": d.isoformat(), "people": len(ok_by[d]), "failed": bad_by[d]} for d in days],
        "policy": [["Sign-in", "email + password"],
                   ["Lock-out", f"{engine_settings().login_max_failures} wrong passwords lock the email and the address for "
                                f"{engine_settings().login_lock_minutes} minutes"],
                   ["Session length", f"{engine_settings().access_token_minutes // 60} hours; signing out or an admin ends it at once"],
                   ["Audit log", "append-only, hash-chained"]],
    }


def engine_settings():
    from app.core.config import get_settings

    return get_settings()


@router.get("/status")
def status(user: User = Depends(Admin)):
    """Small summary for the console's top bar."""
    h = health.health()
    ms = {m.exchange: m for m in market_status.all_statuses()}
    from app.admin import switches

    return {"system": h["status"], "nse": ms["NSE"].label, "mcx": ms["MCX"].label, "nse_open": ms["NSE"].is_open, "mcx_open": ms["MCX"].is_open,
            "orders_enabled": switches.get("orders_enabled"), "engine_enabled": switches.get("engine_enabled")}


# ------------------------------------------------------------------------------------------------------------------- users
@router.get("/users")
def list_users(user: User = Depends(Admin), db: Session = Depends(get_db)):
    rows = _user_rows(db)
    for r in rows:
        target = db.get(User, r["id"])
        r["can_manage"] = perms.can_manage(user, target)
        r["can_view_as"] = r["can_manage"] and r["is_active"]
    return {"users": rows, "assignable_roles": [r for r in ("user", "admin", "developer") if perms.can_assign(user, r)],
            "signup_open": __import__("app.admin.switches", fromlist=["get"]).get("signup_enabled")}


@router.post("/users", status_code=201)
def create_user(body: NewUserIn, user: User = Depends(Admin), db: Session = Depends(get_db)):
    if not perms.can_assign(user, body.role):
        raise HTTPException(403, f"You cannot create a {body.role}")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    pw = _temp_password()
    u = User(email=email, name=body.name.strip(), password_hash=hash_password(pw), role=body.role, is_active=True)
    db.add(u)
    db.commit()
    ensure_default_strategies(db, u.id)
    audit.record("user.create", user, f"user:{u.id}", {"email": email, "role": body.role})
    return {"id": u.id, "email": email, "temporary_password": pw}


def _target(db: Session, actor: User, uid: int) -> User:
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404, "User not found")
    if not perms.can_manage(actor, t):
        raise HTTPException(403, "You can only manage people ranked below you (and never yourself)")
    return t


def _developers(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "developer", User.is_active.is_(True))) or 0


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatchIn, user: User = Depends(Admin), db: Session = Depends(get_db)):
    t = _target(db, user, uid)
    changes = {}
    if body.role is not None and body.role != t.role:
        if not perms.can_assign(user, body.role):
            raise HTTPException(403, f"You cannot make someone a {body.role}")
        if t.role == "developer" and _developers(db) <= 1:
            raise HTTPException(400, "The last developer cannot be demoted")
        changes["role"] = [t.role, body.role]
        t.role = body.role
    if body.is_active is not None and body.is_active != t.is_active:
        if not body.is_active and t.role == "developer" and _developers(db) <= 1:
            raise HTTPException(400, "The last developer cannot be disabled")
        changes["is_active"] = [t.is_active, body.is_active]
        t.is_active = body.is_active
    db.commit()
    if body.is_active is False:
        revoke_sessions(db, t.id)
    if changes:
        audit.record("user.disable" if body.is_active is False else "user.enable" if body.is_active else "user.role", user, f"user:{t.id}", changes)
    return {"ok": True}


@router.post("/users/{uid}/signout")
def signout_user(uid: int, user: User = Depends(Admin), db: Session = Depends(get_db)):
    t = _target(db, user, uid)
    n = revoke_sessions(db, t.id)
    audit.record("user.signout", user, f"user:{t.id}", {"sessions": n})
    return {"sessions_ended": n}


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, user: User = Depends(Admin), db: Session = Depends(get_db)):
    t = _target(db, user, uid)
    pw = _temp_password()
    t.password_hash = hash_password(pw)
    db.commit()
    revoke_sessions(db, t.id)
    audit.record("user.password_reset", user, f"user:{t.id}")
    return {"temporary_password": pw}


@router.delete("/users/{uid}")
def remove_user(uid: int, user: User = Depends(Admin), db: Session = Depends(get_db)):
    t = _target(db, user, uid)
    if t.role == "developer" and _developers(db) <= 1:
        raise HTTPException(400, "The last developer cannot be removed")
    email = t.email
    db.delete(t)                                               # portfolios, orders and positions go with the account (cascade)
    db.commit()
    audit.record("user.remove", user, f"user:{uid}", {"email": email})
    return {"ok": True}


@router.post("/users/{uid}/view-as")
def view_as(uid: int, request: Request, user: User = Depends(Admin), db: Session = Depends(get_db)):
    """A 30-minute read-only session as that person: every change is refused; passwords and keys are never part of any page."""
    t = _target(db, user, uid)
    if not t.is_active:
        raise HTTPException(400, "That account is disabled")
    token = open_session(db, t, request, read_only=True, viewer_id=user.id, minutes=30)
    audit.record("user.view_as", user, f"user:{t.id}")
    return {"token": token, "name": t.name}


# ------------------------------------------------------------------------------------------------------------------- audit log
@router.get("/audit")
def audit_log(q: str = "", limit: int = 300, user: User = Depends(Admin), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(AuditLog.action.like(like) | AuditLog.actor.like(like) | AuditLog.target.like(like) | AuditLog.detail.like(like))
    rows = db.scalars(stmt.limit(max(1, min(limit, 2000)))).all()
    intact, n, broken = audit.verify(db)
    return {"intact": intact, "rows_checked": n, "broken_at": broken,
            "items": [{"id": r.id, "ts": _iso(r.ts), "action": r.action, "actor": r.actor, "target": r.target,
                       "detail": json.loads(r.detail) if r.detail else None} for r in rows]}


# ------------------------------------------------------------------------------------------------------------------- announcements
def _ann(a: Announcement) -> dict:
    return {"id": a.id, "title": a.title, "body": a.body, "level": a.level, "active": a.active, "created_by": a.created_by,
            "created_at": _iso(a.created_at)}


@public_router.get("/announcements")
def active_announcements(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_ann(a) for a in db.scalars(select(Announcement).where(Announcement.active.is_(True)).order_by(Announcement.id.desc()).limit(3))]


@router.get("/announcements")
def list_announcements(user: User = Depends(Admin), db: Session = Depends(get_db)):
    return [_ann(a) for a in db.scalars(select(Announcement).order_by(Announcement.id.desc()).limit(100))]


@router.post("/announcements", status_code=201)
def create_announcement(body: AnnouncementIn, user: User = Depends(Admin), db: Session = Depends(get_db)):
    a = Announcement(title=body.title.strip(), body=body.body.strip(), level=body.level, active=body.active, created_by=audit.actor_name(user))
    db.add(a)
    db.commit()
    audit.record("announcement.create", user, f"announcement:{a.id}", {"title": a.title})
    return _ann(a)


@router.put("/announcements/{aid}")
def update_announcement(aid: int, body: AnnouncementIn, user: User = Depends(Admin), db: Session = Depends(get_db)):
    a = db.get(Announcement, aid)
    if not a:
        raise HTTPException(404, "Announcement not found")
    a.title, a.body, a.level, a.active = body.title.strip(), body.body.strip(), body.level, body.active
    db.commit()
    audit.record("announcement.update", user, f"announcement:{a.id}", {"active": a.active})
    return _ann(a)


@router.delete("/announcements/{aid}")
def delete_announcement(aid: int, user: User = Depends(Admin), db: Session = Depends(get_db)):
    a = db.get(Announcement, aid)
    if not a:
        raise HTTPException(404, "Announcement not found")
    db.delete(a)
    db.commit()
    audit.record("announcement.delete", user, f"announcement:{aid}")
    return {"ok": True}


# ------------------------------------------------------------------------------------------------------------------- market calendar
@router.get("/calendar")
def list_calendar(user: User = Depends(Admin), db: Session = Depends(get_db)):
    since = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    rows = db.scalars(select(MarketCalendarRow).where(MarketCalendarRow.date >= since).order_by(MarketCalendarRow.date)).all()
    return {"entries": [{"date": r.date, "exchange": r.exchange, "kind": r.kind, "start": r.start_time, "end": r.end_time, "note": r.note}
                        for r in rows],
            "status": [m.as_dict() for m in market_status.all_statuses()]}


@router.post("/calendar", status_code=201)
def put_calendar(body: CalendarIn, user: User = Depends(Admin), db: Session = Depends(get_db)):
    try:
        calendar.put(db, body.date.isoformat(), body.exchange, body.kind, body.start, body.end, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record("calendar.put", user, f"{body.exchange}:{body.date}", body.model_dump(mode="json"))
    return {"ok": True}


@router.delete("/calendar/{day}/{exchange}")
def delete_calendar(day: dt.date, exchange: str, user: User = Depends(Admin), db: Session = Depends(get_db)):
    row = db.scalar(select(MarketCalendarRow).where(MarketCalendarRow.date == day.isoformat(),
                                                    MarketCalendarRow.exchange == calendar.canon(exchange.upper())))
    if not row:
        raise HTTPException(404, "No calendar entry for that day")
    db.delete(row)
    db.commit()
    calendar.invalidate()
    audit.record("calendar.delete", user, f"{exchange.upper()}:{day}")
    return {"ok": True}


@router.post("/calendar/sync-nse")
def sync_calendar(user: User = Depends(Admin), db: Session = Depends(get_db)):
    try:
        n = calendar.sync_nse(db)
    except Exception as e:  # noqa: BLE001  (NSE often refuses automated requests)
        raise HTTPException(502, f"NSE did not answer ({type(e).__name__}). Add holidays by hand, or try again later.")
    audit.record("calendar.sync_nse", user, "NSE", {"holidays": n})
    return {"holidays": n}
