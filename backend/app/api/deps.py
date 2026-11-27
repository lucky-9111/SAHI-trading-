from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import TradingAccount, User


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    scheme, _, token = authorization.partition(" ")
    uid = decode_access_token(token) if scheme.lower() == "bearer" else None
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


def owned_account(account_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> TradingAccount:
    """Authorization: an account is only reachable by its owner (portfolio separation)."""
    acc = db.get(TradingAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "Account not found")
    return acc
