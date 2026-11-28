from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.admin import audit, switches
from app.api.deps import current_user
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.database.session import get_db
from app.models import User
from app.models.admin import LoginAttempt, UserSession
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.services.accounts import ensure_default_strategies

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return (fwd or request.headers.get("x-real-ip") or (request.client.host if request.client else ""))[:64]


def device_of(request: Request) -> str:
    ua = request.headers.get("user-agent", "")
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
                    if k in ua), "Browser")
    os_ = next((n for k, n in (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iOS"), ("Windows", "Windows"), ("Mac OS", "macOS"),
                               ("Linux", "Linux")) if k in ua), "")
    return f"{browser} · {os_}" if os_ else browser


def user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.read_only = bool(getattr(user, "_read_only", False))
    return out


def open_session(db: Session, user: User, request: Request, read_only: bool = False, viewer_id: int | None = None,
                 minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    minutes = minutes or get_settings().access_token_minutes
    s = UserSession(user_id=user.id, device=device_of(request), ip=client_ip(request), read_only=read_only, viewer_id=viewer_id,
                    created_at=now, last_seen=now, expires_at=now + timedelta(minutes=minutes))
    db.add(s)
    db.commit()
    return create_access_token(user.id, s.id, minutes)


def revoke_sessions(db: Session, user_id: int, except_id: int | None = None) -> int:
    q = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_id is not None:
        q = q.where(UserSession.id != except_id)
    n = db.execute(q.values(revoked_at=datetime.now(timezone.utc))).rowcount or 0
    db.commit()
    return n


def locked_for(db: Session, email: str, ip: str) -> int:
    """Minutes left on a lock (0 = not locked): too many failures for this email, or from this address, inside the window."""
    s = get_settings()
    since = datetime.now(timezone.utc) - timedelta(minutes=s.login_lock_minutes)
    fails = LoginAttempt.success.is_(False) & (LoginAttempt.reason == "bad_credentials") & (LoginAttempt.ts >= since)
    for cond in [LoginAttempt.email == email] + ([LoginAttempt.ip == ip] if ip else []):
        rows = db.scalars(select(LoginAttempt.ts).where(fails, cond).order_by(LoginAttempt.ts.desc()).limit(s.login_max_failures)).all()
        if len(rows) >= s.login_max_failures:
            oldest = rows[-1] if rows[-1].tzinfo else rows[-1].replace(tzinfo=timezone.utc)
            left = (oldest + timedelta(minutes=s.login_lock_minutes) - datetime.now(timezone.utc)).total_seconds()
            if left > 0:
                return max(1, int(left // 60) + 1)
    return 0


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    first = not db.scalar(select(func.count()).select_from(User))
    if not first and not switches.get("signup_enabled"):
        raise HTTPException(403, "Sign-up is closed. Ask an administrator to add you.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    # the very first account of a new installation owns it (developer + owner); everyone else starts as a user
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
                role="developer" if first else "user", is_owner=first, is_active=True)
    db.add(user)
    db.commit()
    ensure_default_strategies(db, user.id)
    token = open_session(db, user, request)
    audit.record("user.register", user, f"user:{user.id}", {"role": user.role, "device": device_of(request), "ip": client_ip(request)})
    return TokenOut(access_token=token, user=user_out(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email, ip, dev = body.email.lower(), client_ip(request), device_of(request)
    left = locked_for(db, email, ip)
    if left:
        db.add(LoginAttempt(email=email, ip=ip, device=dev, success=False, reason="locked"))
        db.commit()
        raise HTTPException(429, f"Too many failed sign-in attempts. Try again in {left} minute{'s' if left > 1 else ''}.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(body.password, user.password_hash):
        db.add(LoginAttempt(email=email, user_id=user.id if user else None, ip=ip, device=dev, success=False, reason="bad_credentials"))
        db.commit()
        raise HTTPException(401, "Invalid email or password")         # never says which part was wrong
    if not user.is_active:
        db.add(LoginAttempt(email=email, user_id=user.id, ip=ip, device=dev, success=False, reason="disabled"))
        db.commit()
        raise HTTPException(403, "This account is disabled. Contact your administrator.")
    db.add(LoginAttempt(email=email, user_id=user.id, ip=ip, device=dev, success=True, reason="ok"))
    db.commit()
    token = open_session(db, user, request)
    audit.record("login.success", user, "", {"device": dev, "ip": ip})
    return TokenOut(access_token=token, user=user_out(user))


@router.post("/logout")
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(UserSession, user._session_id)
    if s and s.revoked_at is None:
        s.revoked_at = datetime.now(timezone.utc)
        db.commit()
    audit.record("logout", user)
    return {"ok": True}


@router.post("/change-password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    revoke_sessions(db, user.id, except_id=user._session_id)          # other devices must sign in again
    audit.record("user.password_change", user, f"user:{user.id}")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)
