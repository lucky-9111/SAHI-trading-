"""Virtual execution engine. No broker is ever contacted; all fills are simulated against prices from pricing.py.

Money rules:
- Opening debits the ledger by (fill notional + entry charges).
- Closing credits the ledger by (released notional + gross P&L - exit charges).
  => round-trip balance change == gross P&L - total charges, exactly (2dp, Decimal).
- Every state change happens under `lock` and inside one DB transaction.
- An order can only be filled once (atomic PENDING -> EXECUTING status flip).
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Order, Position, Strategy, Trade, TradingAccount
from app.models.core import utcnow
from app.models.market import Instrument
from app.services import accounts as acct
from app.trading import pricing
from app.trading.charges import CASH_PRODUCTS, DERIV_PRODUCTS, estimate_charges, q2, required_cash

log = logging.getLogger(__name__)
lock = threading.RLock()


class TradingError(ValueError):
    pass


def validate_levels(side: str, entry: Decimal, sl: Decimal | None, target: Decimal | None) -> list[str]:
    errs = []
    if side == "BUY":
        if sl is not None and sl >= entry:
            errs.append("Stop-loss must be below the entry price for a BUY order")
        if target is not None and target <= entry:
            errs.append("Target must be above the entry price for a BUY order")
    else:
        if sl is not None and sl <= entry:
            errs.append("Stop-loss must be above the entry price for a SELL order")
        if target is not None and target >= entry:
            errs.append("Target must be below the entry price for a SELL order")
    return errs


def validate_contract(inst: Instrument, side: str, product: str, quantity: int) -> None:
    """Product / lot / expiry rules per instrument type."""
    if inst.instrument_type == "EQ":
        if product not in CASH_PRODUCTS:
            raise TradingError("Choose Intraday, Delivery or Swing for stocks")
        if product in ("DELIVERY", "SWING") and side == "SELL":
            raise TradingError(f"Short selling is not allowed for {product.lower()} orders")
        return
    if product not in DERIV_PRODUCTS:
        raise TradingError("Choose Intraday or Carry-forward (NRML) for futures and options")
    if inst.expiry and inst.expiry < datetime.now(pricing.IST).date():
        raise TradingError(f"{inst.symbol} has expired")
    if quantity % inst.lot_size:
        raise TradingError(f"Quantity must be a multiple of the lot size ({inst.lot_size})")


def settle_expiring_positions(db: Session) -> list[str]:
    """On expiry day after 15:25 IST, close open F&O positions at the latest traded price (reason EXPIRY).
    This is an approximation: real expiry settlement uses an official settlement price this app does not have."""
    now = datetime.now(pricing.IST)
    if now.hour * 60 + now.minute < 15 * 60 + 25 or not pricing.is_market_open(now):
        return []
    events = []
    rows = db.execute(select(Position, Instrument).join(Instrument, Instrument.id == Position.instrument_id)
                      .where(Position.status == "OPEN", Instrument.expiry == now.date())).all()
    for pos, inst in rows:
        try:
            quote = pricing.get_price(inst, max_age=0)
            exit_position(db, pos, None, quote.price, "EXPIRY")
            events.append(f"position {pos.id} settled at expiry @ {quote.price}")
        except (pricing.PriceUnavailable, TradingError) as e:
            log.warning("Expiry settlement skipped for position %s: %s", pos.id, e)
    return events


def _ist_day_start() -> datetime:
    now = datetime.now(pricing.IST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def realized_since(db: Session, account_id: int, since: datetime) -> Decimal:
    v = db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(
        Trade.account_id == account_id, Trade.exit_time >= since))
    return Decimal(str(v))


def check_risk(db: Session, account: TradingAccount, opening_new: bool) -> None:
    rs = account.risk
    if opening_new:
        n = db.scalar(select(func.count()).select_from(Position).where(
            Position.account_id == account.id, Position.status == "OPEN"))
        if n >= rs.max_open_positions:
            raise TradingError(f"Maximum open positions ({rs.max_open_positions}) reached")
    if rs.strict_protection:
        if rs.max_daily_loss and realized_since(db, account.id, _ist_day_start()) <= -rs.max_daily_loss:
            raise TradingError("Daily loss limit reached. New orders are blocked by strict risk protection")
        if rs.max_weekly_loss:
            week = _ist_day_start() - timedelta(days=datetime.now(pricing.IST).weekday())
            if realized_since(db, account.id, week) <= -rs.max_weekly_loss:
                raise TradingError("Weekly loss limit reached. New orders are blocked by strict risk protection")


def open_position(db: Session, account_id: int, instrument_id: int, product: str) -> Position | None:
    return db.scalar(select(Position).where(
        Position.account_id == account_id, Position.instrument_id == instrument_id,
        Position.product == product, Position.status == "OPEN"))


def _reject(db: Session, order: Order, reason: str) -> Order:
    db.rollback()
    order = db.get(Order, order.id)
    order.status, order.reject_reason = "REJECTED", reason[:255]
    db.commit()
    return order


def fill_order(db: Session, order: Order, price: Decimal) -> Order:
    """Fill a PENDING order at `price`. Safe to call repeatedly: only the first call has any effect."""
    with lock:
        flipped = db.execute(update(Order).where(Order.id == order.id, Order.status == "PENDING")
                             .values(status="EXECUTING")).rowcount
        if not flipped:
            db.rollback()
            return db.get(Order, order.id)
        order = db.get(Order, order.id)
        account = db.get(TradingAccount, order.account_id)
        inst = db.get(Instrument, order.instrument_id)
        price = q2(price)
        notional = q2(price * order.quantity)
        cash = required_cash(inst.instrument_type, order.side, price, order.quantity, inst.strike)
        charges = estimate_charges(order.product, order.side, notional, inst.instrument_type)
        pos = open_position(db, order.account_id, order.instrument_id, order.product)
        if pos and pos.side != order.side:
            return _reject(db, order, "Opposite position is open. Exit it first")
        try:
            acct.post_entry(db, account, "ORDER_FILL", -(cash + charges),
                            f"{order.side} {order.quantity} {inst.symbol} @ {price}", f"order-{order.id}-fill")
        except acct.LedgerError:
            return _reject(db, order, "Insufficient virtual funds")
        if pos:
            pos.quantity += order.quantity
            pos.invested_amount += cash
            pos.entry_value += notional
            pos.entry_charges += charges
        else:
            pos = Position(account_id=order.account_id, instrument_id=order.instrument_id, side=order.side,
                           product=order.product, quantity=order.quantity, invested_amount=cash,
                           entry_value=notional, entry_charges=charges, strategy_id=order.strategy_id)
            db.add(pos)
        if order.stop_loss is not None:
            pos.stop_loss = order.stop_loss
        if order.target is not None:
            pos.target = order.target
        order.status, order.exec_price, order.executed_at = "EXECUTED", price, utcnow()
        db.commit()
        return order


def place_order(db: Session, account: TradingAccount, inst: Instrument, *, side: str, order_type: str, product: str,
                quantity: int, limit_price: Decimal | None, stop_loss: Decimal | None, target: Decimal | None,
                strategy_id: int | None, idempotency_key: str | None, validity: str = "DAY") -> Order:
    with lock:
        if idempotency_key:
            dup = db.scalar(select(Order).where(Order.account_id == account.id,
                                                Order.idempotency_key == idempotency_key))
            if dup:
                return dup
        if quantity <= 0:
            raise TradingError("Quantity must be positive")
        validate_contract(inst, side, product, quantity)
        if order_type in ("LIMIT", "TRIGGER") and not limit_price:
            raise TradingError(f"{'Trigger' if order_type == 'TRIGGER' else 'Limit'} price is required")
        if validity == "GTT" and product == "INTRADAY":
            raise TradingError("Intraday orders are valid for the day only")
        if strategy_id is not None:
            st = db.get(Strategy, strategy_id)
            if not st or st.user_id != account.user_id:
                raise TradingError("Unknown strategy")
        existing = open_position(db, account.id, inst.id, product)
        if existing and existing.side != side:
            raise TradingError("Opposite position is open for this stock. Exit it first")
        check_risk(db, account, opening_new=existing is None)

        quote = None
        try:
            quote = pricing.get_price(inst)
        except pricing.PriceUnavailable as e:
            if order_type == "MARKET":
                raise  # never fill a market order without a real price
            log.info("Limit order placed without a price quote: %s", e)
        ref = limit_price if order_type in ("LIMIT", "TRIGGER") else quote.price
        errs = validate_levels(side, ref, stop_loss, target)
        if errs:
            raise TradingError("; ".join(errs))
        if order_type == "TRIGGER" and quote:  # a trigger that is already hit would be a market order
            if side == "BUY" and limit_price <= quote.price:
                raise TradingError("Trigger price must be above the current price for a BUY order")
            if side == "SELL" and limit_price >= quote.price:
                raise TradingError("Trigger price must be below the current price for a SELL order")

        order = Order(account_id=account.id, instrument_id=inst.id, side=side, order_type=order_type,
                      product=product, quantity=quantity, limit_price=limit_price, stop_loss=stop_loss,
                      target=target, strategy_id=strategy_id, idempotency_key=idempotency_key, status="PENDING",
                      validity=validity, expires_at=pricing.session_close().astimezone(timezone.utc) if validity == "DAY" else None)
        db.add(order)
        db.commit()

        if order_type == "MARKET":
            return fill_order(db, order, quote.price)
        if order_type == "LIMIT" and quote and quote.market_open:  # marketable limit fills at the better price
            if (side == "BUY" and quote.price <= limit_price) or (side == "SELL" and quote.price >= limit_price):
                return fill_order(db, order, quote.price)
        return order


def expire_orders(db: Session, now: datetime | None = None) -> int:
    """Cancel pending DAY orders whose session has ended. GTT orders (no expires_at) are untouched."""
    now = now or utcnow()
    with lock:
        n = db.execute(update(Order).where(Order.status == "PENDING", Order.expires_at.is_not(None),
                                           Order.expires_at <= now)
                       .values(status="CANCELLED", reject_reason="Day order expired")).rowcount
        db.commit()
    return n or 0


def cancel_order(db: Session, order: Order) -> Order:
    with lock:
        n = db.execute(update(Order).where(Order.id == order.id, Order.status == "PENDING")
                       .values(status="CANCELLED")).rowcount
        db.commit()
        if not n:
            raise TradingError("Only pending orders can be cancelled")
        return db.get(Order, order.id)


def exit_position(db: Session, pos: Position, quantity: int | None, price: Decimal, reason: str = "MANUAL") -> Trade:
    with lock:
        pos = db.get(Position, pos.id)
        db.refresh(pos)
        if pos.status != "OPEN":
            raise TradingError("Position is already closed")
        qty = quantity or pos.quantity
        if qty <= 0 or qty > pos.quantity:
            raise TradingError(f"Exit quantity must be between 1 and {pos.quantity}")
        account = db.get(TradingAccount, pos.account_id)
        inst = db.get(Instrument, pos.instrument_id)
        price = q2(price)
        last = qty == pos.quantity
        released_cash = pos.invested_amount if last else q2(pos.invested_amount * qty / pos.quantity)
        released = pos.entry_value if last else q2(pos.entry_value * qty / pos.quantity)  # contract value basis
        entry_share = pos.entry_charges if last else q2(pos.entry_charges * qty / pos.quantity)
        proceeds = q2(price * qty)
        gross = proceeds - released if pos.side == "BUY" else released - proceeds
        exit_leg = "SELL" if pos.side == "BUY" else "BUY"
        exit_charges = estimate_charges(pos.product, exit_leg, proceeds, inst.instrument_type)
        credit = released_cash + gross - exit_charges
        try:
            acct.post_entry(db, account, "POSITION_EXIT", credit,
                            f"Exit {qty} {inst.symbol} @ {price} ({reason})")
        except acct.LedgerError as e:
            db.rollback()
            raise TradingError(str(e))
        total_charges = entry_share + exit_charges
        trade = Trade(account_id=pos.account_id, position_id=pos.id, instrument_id=pos.instrument_id, side=pos.side,
                      quantity=qty, entry_price=(released / qty).quantize(Decimal("0.0001")), exit_price=price,
                      gross_pnl=gross, charges=total_charges, net_pnl=gross - total_charges, exit_reason=reason,
                      strategy_id=pos.strategy_id, entry_time=pos.opened_at, exit_time=utcnow())
        db.add(trade)
        pos.quantity -= qty
        pos.invested_amount -= released_cash
        pos.entry_value -= released
        pos.entry_charges -= entry_share
        if last:
            pos.status, pos.closed_at = "CLOSED", utcnow()
        db.commit()
        return trade


def modify_position(db: Session, pos: Position, stop_loss: Decimal | None, target: Decimal | None,
                    clear_sl: bool, clear_target: bool, ref_price: Decimal) -> Position:
    with lock:
        pos = db.get(Position, pos.id)
        if pos.status != "OPEN":
            raise TradingError("Position is closed")
        new_sl = None if clear_sl else (stop_loss if stop_loss is not None else pos.stop_loss)
        new_t = None if clear_target else (target if target is not None else pos.target)
        errs = validate_levels(pos.side, ref_price, new_sl, new_t)
        if errs:
            raise TradingError("; ".join(errs) + f" (current price {ref_price})")
        pos.stop_loss, pos.target = new_sl, new_t
        db.commit()
        return pos


def process_price(db: Session, instrument_id: int, price: Decimal) -> list[str]:
    """Apply one observed price to pending orders and open positions. Returns event descriptions.
    Gaps: fills happen at the observed price, which may be worse than the stop-loss level."""
    events: list[str] = []
    with lock:
        for o in db.scalars(select(Order).where(Order.instrument_id == instrument_id, Order.status == "PENDING",
                                                Order.order_type.in_(["LIMIT", "TRIGGER"]))).all():
            if o.order_type == "LIMIT":  # buy at or below / sell at or above the limit
                hit = (o.side == "BUY" and price <= o.limit_price) or (o.side == "SELL" and price >= o.limit_price)
            else:  # trigger (stop) order: buy once price rises to it, sell once it falls to it; fills at observed price
                hit = (o.side == "BUY" and price >= o.limit_price) or (o.side == "SELL" and price <= o.limit_price)
            if hit:
                res = fill_order(db, o, price)
                events.append(f"order {o.id} {res.status}")
        for p in db.scalars(select(Position).where(Position.instrument_id == instrument_id,
                                                   Position.status == "OPEN")).all():
            long_ = p.side == "BUY"
            reason = None
            if p.stop_loss is not None and ((long_ and price <= p.stop_loss) or (not long_ and price >= p.stop_loss)):
                reason = "STOP_LOSS"
            elif p.target is not None and ((long_ and price >= p.target) or (not long_ and price <= p.target)):
                reason = "TARGET"
            if reason:
                try:
                    exit_position(db, p, None, price, reason)
                    events.append(f"position {p.id} closed by {reason} @ {price}")
                except TradingError as e:
                    log.warning("Auto exit skipped for position %s: %s", p.id, e)
    return events
