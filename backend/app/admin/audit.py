"""Append-only audit log with a hash chain: each row's hash covers its own fields and the previous row's hash, so editing or removing
any row breaks `verify()`. The database also refuses UPDATE / DELETE on the table (SQLite triggers in app.models.admin)."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import AuditLog, User

_lock = threading.Lock()


def _digest(prev: str, ts: datetime, actor: str, action: str, target: str, detail: str) -> str:
    stamp = ts.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
    raw = json.dumps([prev, stamp, actor, action, target, detail], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def actor_name(user: User | None) -> str:
    return "system" if user is None else (user.email.split("@")[0] if user.email else f"user:{user.id}")


def record(action: str, actor: User | None = None, target: str = "", detail: dict | None = None, session_factory=SessionLocal) -> None:
    """Write one row in its own transaction (call it after the action itself committed)."""
    body = json.dumps(detail or {}, separators=(",", ":"), ensure_ascii=False, default=str) if detail else ""
    name = actor_name(actor)
    with _lock, session_factory() as db:
        last = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
        prev = last.hash if last else ""
        ts = datetime.now(timezone.utc)
        db.add(AuditLog(ts=ts, actor_id=actor.id if actor else None, actor=name, action=action, target=target[:120], detail=body,
                        prev_hash=prev, hash=_digest(prev, ts, name, action, target[:120], body)))
        db.commit()


def verify(db) -> tuple[bool, int, int | None]:
    """(intact, rows checked, first broken row id)."""
    prev = ""
    n = 0
    for r in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        n += 1
        ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=timezone.utc)
        if r.prev_hash != prev or r.hash != _digest(prev, ts, r.actor, r.action, r.target, r.detail):
            return False, n, r.id
        prev = r.hash
    return True, n, None
