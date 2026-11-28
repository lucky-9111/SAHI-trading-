"""Notifications / order activity of the signed-in user. Order events are pushed over /ws/ticks as they happen; this is the catch-up and
history source (a tab that was closed or offline reads what it missed with ?after_id=)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database.session import get_db
from app.models import Notification, User
from app.trading.notify import as_dict

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class ReadIn(BaseModel):
    ids: list[int] | None = None   # None = all


@router.get("")
def list_notifications(after_id: int = 0, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    q = select(Notification).where(Notification.user_id == user.id)
    if after_id:
        rows = db.scalars(q.where(Notification.id > after_id).order_by(Notification.id).limit(limit)).all()
    else:
        rows = list(reversed(db.scalars(q.order_by(Notification.id.desc()).limit(limit)).all()))
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user.id,
                                                                            Notification.is_read.is_(False))) or 0
    latest = db.scalar(select(func.max(Notification.id)).where(Notification.user_id == user.id)) or 0
    return {"items": [as_dict(n) for n in rows], "unread": unread, "latest_id": latest}


@router.post("/read")
def mark_read(body: ReadIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = update(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False))
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    db.execute(q.values(is_read=True))
    db.commit()
    return {"ok": True}
