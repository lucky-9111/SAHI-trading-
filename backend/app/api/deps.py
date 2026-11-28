from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database.session import get_db
from app.models import TradingAccount, User
from app.models.admin import UserSession

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TOUCH_EVERY = timedelta(seconds=30)


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def current_user(request: Request, authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    """The signed-in user. The token must name a live session: signed out, revoked by an admin, expired or a disabled user -> 401.
    A read-only "view as" session can only read (GET)."""
    scheme, _, token = authorization.partition(" ")
    data = decode_token(token) if scheme.lower() == "bearer" else None
    if not data or "sid" not in data:
        raise HTTPException(401, "Not authenticated")
    sess = db.get(UserSession, data["sid"])
    now = datetime.now(timezone.utc)
    if not sess or sess.user_id != data["sub"] or sess.revoked_at is not None or _utc(sess.expires_at) < now:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    user = db.get(User, data["sub"])
    if not user or not user.is_active:
        raise HTTPException(401, "Not authenticated")
    if sess.read_only and request.method not in SAFE_METHODS:
        raise HTTPException(403, "Read-only view: changes are not allowed while viewing as another user")
    if now - _utc(sess.last_seen) > TOUCH_EVERY:
        sess.last_seen = now
        db.commit()
    user._read_only = bool(sess.read_only)
    user._session_id = sess.id
    return user


def owned_account(account_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> TradingAccount:
    """Authorization: an account is only reachable by its owner (portfolio separation)."""
    acc = db.get(TradingAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "Account not found")
    return acc
