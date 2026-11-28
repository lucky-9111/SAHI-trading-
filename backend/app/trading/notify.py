"""Order notifications.

Every order event is one `Notification` row written in the SAME transaction as the state change it describes, so a notification exists if
and only if the change was committed (a rolled-back fill leaves no "executed" message behind). The rows double as the order's status
history. After the commit each new row is pushed to the user's open browser tabs (websocket event "notification"); tabs that missed the
push read them from GET /api/notifications.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models import Notification, Order, TradingAccount
from app.models.market import Instrument

log = logging.getLogger(__name__)

# kind -> (title, level)
KINDS = {
    "ORDER_PLACED": ("Order placed successfully", "info"),
    "ORDER_PENDING_CLOSED": ("Order pending – market closed", "warning"),
    "ORDER_PENDING_PRICE": ("Order pending – waiting for a live price", "warning"),
    "ORDER_OPEN": ("Order open at market open", "info"),
    "ORDER_TRIGGERED": ("Stop-loss triggered", "info"),
    "ORDER_PARTIAL": ("Order partially executed", "success"),
    "ORDER_FILLED": ("Order executed successfully", "success"),
    "ORDER_REJECTED": ("Order rejected", "error"),
    "ORDER_CANCELLED": ("Order cancelled", "info"),
    "ORDER_EXPIRED": ("Order expired", "warning"),
}
TYPE_LABEL = {"MARKET": "Market", "LIMIT": "Limit", "SL": "SL", "SL-M": "SL-M"}


def money(x: Decimal | None) -> str:
    if x is None:
        return "-"
    q = Decimal(x).quantize(Decimal("0.01"))
    whole, frac = f"{abs(q):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]                 # Indian digit grouping: 12,34,567.89
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{'-' if q < 0 else ''}₹{','.join(groups + [tail]) if groups else tail}.{frac}"


def order_event(db: Session, order: Order, kind: str, detail: str = "", title: str | None = None) -> Notification:
    """Record an order event inside the caller's transaction; it is pushed to the browser once that transaction commits."""
    from app.trading import market_status

    acc = db.get(TradingAccount, order.account_id)
    inst = db.get(Instrument, order.instrument_id)
    t, level = KINDS[kind]
    head = f"{order.side} {order.quantity} {inst.symbol if inst else ''} · {TYPE_LABEL.get(order.order_type, order.order_type)}"
    n = Notification(user_id=acc.user_id, account_id=acc.id, order_id=order.id, kind=kind, level=level, title=title or t,
                     body=f"{head}{f' · {detail}' if detail else ''}", created_at=market_status.now())
    db.add(n)
    db.info.setdefault("outbox", []).append(n)
    return n


def as_dict(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "level": n.level, "title": n.title, "body": n.body, "order_id": n.order_id,
            "account_id": n.account_id, "is_read": n.is_read, "created_at": n.created_at.isoformat() if n.created_at else None}


@event.listens_for(SessionLocal, "after_commit")
def _push_after_commit(session: Session) -> None:
    out = session.info.pop("outbox", None)
    if not out:
        return
    from app.live import runtime

    for n in out:
        try:
            runtime.notify_user(n.user_id, {"type": "notification", "notification": as_dict(n)})
        except Exception:  # noqa: BLE001  (a push failure must never undo a committed fill)
            log.exception("notification push failed")


@event.listens_for(SessionLocal, "after_rollback")
def _drop_on_rollback(session: Session) -> None:
    session.info.pop("outbox", None)
