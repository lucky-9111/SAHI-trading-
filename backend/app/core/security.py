from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, sid: int | None = None, minutes: int | None = None) -> str:
    """A signed token naming the user and the sign-in session (UserSession id). Revoking the session ends the token."""
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes or s.access_token_minutes)
    payload = {"sub": str(user_id), "exp": exp}
    if sid is not None:
        payload["sid"] = sid
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        data["sub"] = int(data["sub"])
        return data
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


def decode_access_token(token: str) -> int | None:
    data = decode_token(token)
    return data["sub"] if data else None
