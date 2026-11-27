"""Glue between the tick stream and the paper order engine (app.trading.engine).

The engine itself (fills, ledger, positions, charges) is unchanged and already idempotent: an order flips PENDING -> EXECUTING in one atomic
UPDATE, a position closes once. Here we only decide WHEN to call it:
  * armed(): instruments that have something to check on a tick (pending limit / trigger orders, open positions with a stop or target);
  * on_tick(): run engine.process_price for an armed instrument (limit, stop, target; a gap fills at the first price seen, not at the stop);
  * square_off_intraday(): INTRADAY positions are closed at the end of their exchange's session with reason EOD.
All functions are synchronous and open their own DB session: the pipeline calls them through asyncio.to_thread.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Callable

from sqlalchemy import select

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.live import calendar
from app.models import Order, Position, TradingAccount
from app.models.market import Instrument
from app.trading import engine

log = logging.getLogger(__name__)
UTC, IST = calendar.UTC, calendar.IST


def armed(session_factory=SessionLocal) -> dict[int, tuple[str, str]]:
    """instrument_id -> (exchange, token) for everything that needs a price check on each tick."""
    with session_factory() as db:
        ids = set(db.scalars(select(Order.instrument_id).where(Order.status == "PENDING", Order.order_type.in_(["LIMIT", "TRIGGER"]))))
        ids |= set(db.scalars(select(Position.instrument_id).where(Position.status == "OPEN",
                                                                   (Position.stop_loss.is_not(None)) | (Position.target.is_not(None)))))
        if not ids:
            return {}
        return {i.id: (i.exchange, i.token) for i in db.scalars(select(Instrument).where(Instrument.id.in_(ids)))}


def open_position_tokens(session_factory=SessionLocal) -> set[tuple[str, str]]:
    """Tokens to keep subscribed because money is at risk in them (any open position or pending order)."""
    with session_factory() as db:
        ids = set(db.scalars(select(Position.instrument_id).where(Position.status == "OPEN")))
        ids |= set(db.scalars(select(Order.instrument_id).where(Order.status == "PENDING")))
        if not ids:
            return set()
        return {(i.exchange, i.token) for i in db.scalars(select(Instrument).where(Instrument.id.in_(ids)))}


def users_of_instrument(db, instrument_id: int) -> set[int]:
    accs = set(db.scalars(select(Position.account_id).where(Position.instrument_id == instrument_id)))
    accs |= set(db.scalars(select(Order.account_id).where(Order.instrument_id == instrument_id)))
    if not accs:
        return set()
    return set(db.scalars(select(TradingAccount.user_id).where(TradingAccount.id.in_(accs))))


def on_tick(instrument_id: int, price: float, session_factory=SessionLocal) -> tuple[list[str], set[int]]:
    """Apply one observed price. Returns (event texts, user ids to notify)."""
    with session_factory() as db:
        events = engine.process_price(db, instrument_id, Decimal(str(price)))
        users = users_of_instrument(db, instrument_id) if events else set()
    return events, users


def square_off_intraday(now: dt.datetime, price_of: Callable[[str, str], float | None], session_factory=SessionLocal) -> tuple[list[str], set[int]]:
    """Close INTRADAY positions whose exchange session has ended (or ends within `intraday_squareoff_minutes_before_close`).

    A position opened on an earlier day (the app was down at the close) is squared off too, at the last price we know.
    `price_of(exchange, token)` returns that price or None; a position without a price is left for the next pass."""
    now = now.astimezone(UTC)
    lead = dt.timedelta(minutes=get_settings().intraday_squareoff_minutes_before_close)
    events: list[str] = []
    users: set[int] = set()
    with session_factory() as db:
        rows = db.execute(select(Position, Instrument).join(Instrument, Instrument.id == Position.instrument_id)
                          .where(Position.status == "OPEN", Position.product == "INTRADAY")).all()
        for pos, inst in rows:
            opened = pos.opened_at if pos.opened_at.tzinfo else pos.opened_at.replace(tzinfo=UTC)
            day = opened.astimezone(IST).date()
            b = calendar.session_bounds(inst.exchange, day)
            end = b[1] if b else dt.datetime.combine(day, dt.time(23, 59), tzinfo=IST).astimezone(UTC)
            if now < end - lead:
                continue
            px = price_of(inst.exchange, inst.token)
            if px is None:
                log.warning("EOD square-off waits for a price: position %s %s", pos.id, inst.symbol)
                continue
            try:
                engine.exit_position(db, pos, None, Decimal(str(px)), "EOD")
                events.append(f"position {pos.id} squared off (EOD) @ {px}")
                acc = db.get(TradingAccount, pos.account_id)
                users.add(acc.user_id)
            except engine.TradingError as e:
                log.warning("EOD square-off skipped for position %s: %s", pos.id, e)
    return events, users
