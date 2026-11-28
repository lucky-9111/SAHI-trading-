"""Paper order management and virtual execution engine. No broker is ever contacted; every fill is simulated against a live price.

Lifecycle (statuses in app.models.trading):
    place_order --market closed--> PENDING (after-market order) or REJECTED (account setting "reject")
                --session open --> MARKET: executes now (or PENDING until the first fresh price)
                                   LIMIT: OPEN       SL / SL-M: TRIGGER_PENDING
    PENDING          --first fresh price of the next session--> MARKET executes, LIMIT -> OPEN, SL / SL-M -> TRIGGER_PENDING
    TRIGGER_PENDING  --price reaches the trigger--> SL-M executes as a market order, SL becomes a limit order (OPEN)
    OPEN             --price reaches the limit--> FILLED or PARTIALLY_FILLED
    working orders   --cancel--> CANCELLED      --DAY validity ends at the session close--> EXPIRED
    any fill that cannot be booked (funds, opposite position) --> REJECTED

Execution rules:
- Orders execute only while the market status engine says the exchange is OPEN, and only on a price that traded in the current session
  (pricing.execution_quote / a websocket tick). Yesterday's LTP is never an execution price; no price means no fill.
- Market and triggered stop-market orders take the opposite side of the broker's 5-level depth when a fresh quote has it (BUY walks the
  asks, SELL the bids), plus the account's adverse slippage. Limit orders fill at the book / observed price, never worse than the limit.
  When the visible size is smaller than the order, the rest stays working (PARTIALLY_FILLED). Without depth the full quantity trades at
  the last traded price.
- An order is filled by an atomic compare-and-swap on (id, filled_quantity, working status): the same price seen twice, by two workers
  or after a restart, can never fill the same quantity twice. Each fill posts one ledger entry with its own idempotency key.

Money rules (unchanged):
- Opening debits the ledger by (fill cash + entry charges); closing credits (released cash + gross P&L - exit charges).
- Every state change happens under `lock` and inside one DB transaction, together with its notification.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.admin import switches
from app.core.config import get_settings
from app.live import calendar
from app.models import Order, Position, Strategy, Trade, TradingAccount
from app.models.live import TradeLog
from app.models.market import Instrument
from app.models.trading import ORDER_TYPES, WORKING_STATUSES
from app.services import accounts as acct
from app.trading import market_status as ms
from app.trading import notify, pricing
from app.trading.charges import CASH_PRODUCTS, DERIV_PRODUCTS, estimate_charges, q2, required_cash

log = logging.getLogger(__name__)
lock = threading.RLock()
UTC = timezone.utc
WORKING = WORKING_STATUSES
Book = Callable[[], tuple[tuple, tuple]]


class TradingError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------------------------- helpers
def slippage_pct(db: Session | None = None, account_id: int | None = None) -> Decimal:
    """The account's slippage setting, else the PAPER_SLIPPAGE_PCT server default."""
    if db is not None and account_id is not None:
        acc = db.get(TradingAccount, account_id)
        if acc and acc.risk and acc.risk.slippage_pct is not None:
            return Decimal(acc.risk.slippage_pct)
    return Decimal(get_settings().paper_slippage_pct or "0")


def slip(side: str, price: Decimal, pct: Decimal | None = None) -> Decimal:
    """Adverse slippage: a BUY fills a little higher, a SELL a little lower. 0 by default."""
    pct = slippage_pct() if pct is None else pct
    if pct <= 0:
        return q2(price)
    return q2(price * (1 + pct / 100)) if side == "BUY" else q2(price * (1 - pct / 100))


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


def validate_contract(inst: Instrument, side: str, product: str, quantity: int, reducing: bool = False) -> None:
    """Product / lot / expiry rules per instrument type. `reducing`: the order exits an open position."""
    if inst.instrument_type == "EQ":
        if product not in CASH_PRODUCTS:
            raise TradingError("Choose Intraday, Delivery or Swing for stocks")
        if product in ("DELIVERY", "SWING") and side == "SELL" and not reducing:
            raise TradingError(f"Short selling is not allowed for {product.lower()} orders")
        return
    if product not in DERIV_PRODUCTS:
        raise TradingError("Choose Intraday or Carry-forward (NRML) for futures and options")
    if inst.expiry and inst.expiry < ms.now().astimezone(pricing.IST).date():
        raise TradingError(f"{inst.symbol} has expired")
    if quantity % inst.lot_size:
        raise TradingError(f"Quantity must be a multiple of the lot size ({inst.lot_size})")


def _ist_day_start() -> datetime:
    now = ms.now().astimezone(pricing.IST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


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
            week = _ist_day_start() - timedelta(days=ms.now().astimezone(pricing.IST).weekday())
            if realized_since(db, account.id, week) <= -rs.max_weekly_loss:
                raise TradingError("Weekly loss limit reached. New orders are blocked by strict risk protection")


def open_position(db: Session, account_id: int, instrument_id: int, product: str) -> Position | None:
    return db.scalar(select(Position).where(
        Position.account_id == account_id, Position.instrument_id == instrument_id,
        Position.product == product, Position.status == "OPEN"))


def _reload(db: Session, order_id: int) -> Order:
    return db.get(Order, order_id, populate_existing=True)


def _cas(db: Session, order_id: int, frm: str, to: str, **values) -> bool:
    """Atomic status transition: only succeeds if the order is still in `frm`."""
    n = db.execute(update(Order).where(Order.id == order_id, Order.status == frm)
                   .values(status=to, updated_at=ms.now(), **values).execution_options(synchronize_session=False)).rowcount
    return bool(n)


def _ist_text(t: datetime | None) -> str:
    return t.astimezone(pricing.IST).strftime("%a %d %b, %H:%M IST") if t else "the next session"


def closed_message(market: "ms.MarketStatus") -> str:
    """'Market closed (Weekend). NSE opens Mon 30 Nov, 09:15 IST. Orders are accepted only during market hours.'"""
    state = {"PRE_OPEN": "pre-open session", "POST_CLOSE": "post-close session", "WEEKEND": "weekend", "HOLIDAY": "exchange holiday"}
    why = state.get(market.state)
    head = f"Market closed{f' ({why})' if why else ''}"
    if market.state == "HOLIDAY" and market.note:
        head = f"Market closed ({market.note})"
    return f"{head}. {market.exchange} opens {_ist_text(market.next_open)}. Orders are accepted only during market hours."


def _display_price(inst: Instrument) -> Decimal | None:
    """Best-effort reference price for validation and the funds check only (may be the last close). Never an execution price."""
    try:
        return pricing.get_price(inst).price
    except pricing.PriceUnavailable:
        return None


def _book(inst: Instrument, at: datetime) -> Book:
    """Lazy, memoized 5-level depth of the current session: fetched only when an order is about to fill."""
    cache: dict = {}

    def get():
        if "v" not in cache:
            b = calendar.session_bounds(inst.exchange, at.astimezone(pricing.IST).date())
            cache["v"] = pricing.depth(inst, b[0]) if b else ((), ())
        return cache["v"]
    return get


def _match(side: str, want: int, ltp: Decimal, limit: Decimal | None, bids: tuple, asks: tuple) -> tuple[int, Decimal | None]:
    """(quantity, average price) the visible book gives this order now. No depth: the whole quantity at the last traded price."""
    book = asks if side == "BUY" else bids
    if not book:
        return want, ltp
    take, cost = 0, Decimal(0)
    for price, size in book:
        if limit is not None and (price > limit if side == "BUY" else price < limit):
            break
        n = min(size, want - take)
        take += n
        cost += price * n
        if take >= want:
            break
    if not take:
        return 0, None
    return take, q2(cost / take)


# ---------------------------------------------------------------------------------------------------------------- placing
def _reject_new(db: Session, order: Order, reason: str) -> Order:
    order.status, order.reject_reason, order.updated_at = "REJECTED", reason[:255], ms.now()
    notify.order_event(db, order, "ORDER_REJECTED", reason)
    db.commit()
    return order


def place_order(db: Session, account: TradingAccount, inst: Instrument, *, side: str, order_type: str, product: str,
                quantity: int, limit_price: Decimal | None, stop_loss: Decimal | None, target: Decimal | None,
                strategy_id: int | None, idempotency_key: str | None, validity: str = "DAY",
                trigger_price: Decimal | None = None) -> Order:
    """Validate and accept an order. Input errors raise TradingError (nothing stored); business refusals (market closed in reject mode,
    insufficient funds, no fresh price in reject mode) are stored as REJECTED orders so they show in the order book."""
    if order_type == "TRIGGER":            # legacy name: a stop-market order whose trigger came in limit_price
        order_type, trigger_price, limit_price = "SL-M", trigger_price or limit_price, None
    with lock:
        if idempotency_key:
            dup = db.scalar(select(Order).where(Order.account_id == account.id, Order.idempotency_key == idempotency_key))
            if dup:
                return dup
        if quantity <= 0:
            raise TradingError("Quantity must be positive")
        if order_type not in ORDER_TYPES:
            raise TradingError("Order type must be MARKET, LIMIT, SL or SL-M")
        if order_type == "MARKET":
            limit_price = trigger_price = None
        elif order_type == "LIMIT":
            trigger_price = None
        elif order_type == "SL-M":
            limit_price = None
        if order_type in ("LIMIT", "SL") and not limit_price:
            raise TradingError("Limit price is required")
        if order_type in ("SL", "SL-M") and not trigger_price:
            raise TradingError("Trigger price is required")
        if order_type == "SL":
            if side == "BUY" and limit_price < trigger_price:
                raise TradingError("For a BUY stop-loss order the limit price must be at or above the trigger price")
            if side == "SELL" and limit_price > trigger_price:
                raise TradingError("For a SELL stop-loss order the limit price must be at or below the trigger price")
        if validity == "GTT" and product == "INTRADAY":
            raise TradingError("Intraday orders are valid for the day only")
        if strategy_id is not None:
            st = db.get(Strategy, strategy_id)
            if not st or st.user_id != account.user_id:
                raise TradingError("Unknown strategy")
        existing = open_position(db, account.id, inst.id, product)
        reducing = existing is not None and existing.side != side
        if reducing:
            if quantity > existing.quantity:
                raise TradingError(f"Exit quantity cannot exceed the open position ({existing.quantity})")
            if stop_loss is not None or target is not None:
                raise TradingError("Stop-loss and target apply to new positions, not to exit orders")
        validate_contract(inst, side, product, quantity, reducing=reducing)
        if not reducing and not switches.get("orders_enabled"):
            raise TradingError("New orders are paused by the administrator. Exits of open positions still work.")
        if not reducing:
            check_risk(db, account, opening_new=existing is None)

        now = ms.now()
        market = ms.status(inst.exchange, now)
        mode = (account.risk.after_hours_mode if account.risk else None) or "REJECT"
        live, live_err = None, ""
        if market.is_open:
            try:
                live = pricing.execution_quote(inst, now)
            except pricing.PriceUnavailable as e:
                live_err = str(e)
        ltp_ref = live.ltp if live else _display_price(inst)
        if order_type in ("SL", "SL-M") and ltp_ref is not None:   # a trigger that is already hit would be a market order
            if side == "BUY" and trigger_price <= ltp_ref:
                raise TradingError(f"Trigger price must be above the current price for a BUY order (current {ltp_ref})")
            if side == "SELL" and trigger_price >= ltp_ref:
                raise TradingError(f"Trigger price must be below the current price for a SELL order (current {ltp_ref})")
        entry_ref = limit_price if order_type in ("LIMIT", "SL") else trigger_price if order_type == "SL-M" else ltp_ref
        if entry_ref is not None and not reducing:
            errs = validate_levels(side, entry_ref, stop_loss, target)
            if errs:
                raise TradingError("; ".join(errs))

        order = Order(account_id=account.id, instrument_id=inst.id, side=side, order_type=order_type, product=product,
                      quantity=quantity, filled_quantity=0, limit_price=limit_price, trigger_price=trigger_price, stop_loss=stop_loss,
                      target=target, strategy_id=strategy_id, idempotency_key=idempotency_key, status="PENDING", validity=validity,
                      after_market=not market.is_open, reduce_only=reducing, created_at=now, updated_at=now,
                      expires_at=pricing.session_close(now, inst.exchange).astimezone(UTC) if validity == "DAY" else None)
        db.add(order)
        db.flush()

        if not market.is_open and validity == "DAY" and mode == "REJECT":
            return _reject_new(db, order, closed_message(market))
        if not reducing and entry_ref is not None:
            need = required_cash(inst.instrument_type, side, entry_ref, quantity, inst.strike) + \
                estimate_charges(product, side, q2(entry_ref * quantity), inst.instrument_type, inst.exchange)
            if need > acct.get_balance(db, account.id):
                return _reject_new(db, order, "Insufficient virtual funds")
        if not market.is_open:
            notify.order_event(db, order, "ORDER_PENDING_CLOSED", f"{market.label}. Executes at a live price after the open "
                                                                 f"({_ist_text(market.next_open)})")
            db.commit()
            return order
        if order_type == "MARKET" and live is None:
            if mode == "REJECT":
                return _reject_new(db, order, f"No fresh market price: {live_err}")
            notify.order_event(db, order, "ORDER_PENDING_PRICE", f"{live_err}. Executes at the first fresh price")
            db.commit()
            return order
        order.status = {"MARKET": "PENDING", "LIMIT": "OPEN", "SL": "TRIGGER_PENDING", "SL-M": "TRIGGER_PENDING"}[order_type]
        db.commit()
        if live is not None:
            _evaluate(db, order.id, inst, live, now, _book(inst, now))   # MARKET executes now; a marketable LIMIT too
        order = _reload(db, order.id)
        if order.status in ("OPEN", "TRIGGER_PENDING") and not order.filled_quantity and order.triggered_at is None:
            notify.order_event(db, order, "ORDER_PLACED", f"limit {notify.money(order.limit_price)}" if order.order_type == "LIMIT"
                               else f"trigger {notify.money(order.trigger_price)}")
            db.commit()
        return order


# ---------------------------------------------------------------------------------------------------------------- executing
def _fail(db: Session, order_id: int, reason: str) -> str | None:
    """A fill could not be booked: undo it and reject the rest of the order (quantity already filled stays filled)."""
    db.rollback()
    o = _reload(db, order_id)
    if o.status not in WORKING:
        return None
    o.status, o.reject_reason, o.updated_at = "REJECTED", reason[:255], ms.now()
    extra = f" · {o.filled_quantity} of {o.quantity} had executed" if o.filled_quantity else ""
    notify.order_event(db, o, "ORDER_REJECTED", reason + extra)
    db.commit()
    return f"order {o.id} REJECTED"


def _fill(db: Session, order_id: int, expected_filled: int, qty: int, price: Decimal) -> str | None:
    """Execute `qty` of a working order at `price`. Only the first call for a given (order, filled quantity) has any effect."""
    with lock:
        now = ms.now()
        n = db.execute(update(Order).where(Order.id == order_id, Order.filled_quantity == expected_filled,
                                           Order.status.in_(WORKING))
                       .values(filled_quantity=expected_filled + qty, updated_at=now)
                       .execution_options(synchronize_session=False)).rowcount
        if not n:
            db.rollback()
            return None
        o = _reload(db, order_id)
        account = db.get(TradingAccount, o.account_id)
        inst = db.get(Instrument, o.instrument_id)
        price = q2(price)
        seq = (db.scalar(select(func.count()).select_from(TradeLog).where(TradeLog.order_id == o.id)) or 0) + 1
        key = f"order-{o.id}-fill-{seq}"                       # one ledger entry per fill, ever
        pos = open_position(db, o.account_id, o.instrument_id, o.product)
        if o.reduce_only:
            if not pos or pos.side == o.side:
                return _fail(db, o.id, "No open position left to exit")
            if qty > pos.quantity:
                return _fail(db, o.id, f"Exit quantity exceeds the open position ({pos.quantity})")
            try:
                exit_position(db, pos, qty, price, "STOP_LOSS" if o.order_type in ("SL", "SL-M") else "MANUAL",
                              order_id=o.id, ledger_key=key, commit=False)
            except TradingError as e:
                return _fail(db, o.id, str(e))
            o = _reload(db, order_id)
        else:
            if pos and pos.side != o.side:
                return _fail(db, o.id, "Opposite position is open. Exit it first")
            notional = q2(price * qty)
            cash = required_cash(inst.instrument_type, o.side, price, qty, inst.strike)
            charges = estimate_charges(o.product, o.side, notional, inst.instrument_type, inst.exchange)
            try:
                acct.post_entry(db, account, "ORDER_FILL", -(cash + charges), f"{o.side} {qty} {inst.symbol} @ {price}", key)
            except acct.LedgerError:
                return _fail(db, o.id, "Insufficient virtual funds")
            if pos:
                pos.quantity += qty
                pos.invested_amount += cash
                pos.entry_value += notional
                pos.entry_charges += charges
            else:
                pos = Position(account_id=o.account_id, instrument_id=o.instrument_id, side=o.side, product=o.product, quantity=qty,
                               invested_amount=cash, entry_value=notional, entry_charges=charges, strategy_id=o.strategy_id,
                               opened_at=now)
                db.add(pos)
            if o.stop_loss is not None:
                pos.stop_loss = o.stop_loss
            if o.target is not None:
                pos.target = o.target
            db.flush()
            db.add(TradeLog(account_id=o.account_id, order_id=o.id, position_id=pos.id, instrument_id=o.instrument_id, event="FILL",
                            side=o.side, quantity=qty, price=price, charges=charges, ts=now,
                            reason="SIGNAL" if (o.idempotency_key or "").startswith("sig-") else "ENTRY"))
        filled = expected_filled + qty
        o.exec_price = q2(((o.exec_price or Decimal(0)) * expected_filled + price * qty) / filled)
        o.executed_at = now
        o.status = "FILLED" if filled >= o.quantity else "PARTIALLY_FILLED"
        if o.status == "FILLED" and expected_filled == 0:
            detail = f"{qty} @ {notify.money(price)}"
        else:
            detail = f"{qty} @ {notify.money(price)} · {filled}/{o.quantity} done · avg {notify.money(o.exec_price)}"
        notify.order_event(db, o, "ORDER_FILLED" if o.status == "FILLED" else "ORDER_PARTIAL", detail)
        db.commit()
        return f"order {o.id} {o.status}"


def _evaluate(db: Session, order_id: int, inst: Instrument, q: "pricing.ExecQuote", at: datetime, book: Book) -> str | None:
    """Apply one fresh in-session price to one working order: activate, trigger, then execute what the price (and book) allows."""
    o = _reload(db, order_id)
    if o is None or o.status not in WORKING:
        return None
    exp = ms.utc(o.expires_at)
    if exp is not None and at > exp:
        return None                                            # the expiry pass finalizes it
    if o.after_market and o.status == "PENDING" and q.at < calendar.next_open(inst.exchange, ms.utc(o.created_at)):
        return None                                            # a price from before this order's first session: never fill on it
    activated = triggered = False
    with lock:
        if o.status == "PENDING" and o.order_type != "MARKET":
            to = "OPEN" if o.order_type == "LIMIT" else "TRIGGER_PENDING"
            if not _cas(db, o.id, "PENDING", to):
                db.rollback()
                return None
            db.commit()
            o, activated = _reload(db, o.id), True
        if o.status == "TRIGGER_PENDING":
            hit = (o.side == "BUY" and q.ltp >= o.trigger_price) or (o.side == "SELL" and q.ltp <= o.trigger_price)
            if not hit:
                if activated:
                    notify.order_event(db, o, "ORDER_OPEN", f"stop-loss live, trigger {notify.money(o.trigger_price)}")
                    db.commit()
                return f"order {o.id} TRIGGER_PENDING" if activated else None
            if not _cas(db, o.id, "TRIGGER_PENDING", "OPEN", triggered_at=at):
                db.rollback()
                return None
            db.commit()
            o, triggered = _reload(db, o.id), True

    market_like = o.order_type in ("MARKET", "SL-M")           # SL-M is OPEN only once triggered
    limit = o.limit_price if o.order_type in ("LIMIT", "SL") else None
    qty, px = 0, None
    if limit is None or (o.side == "BUY" and q.ltp <= limit) or (o.side == "SELL" and q.ltp >= limit):
        bids, asks = (q.bids, q.asks) if (q.bids or q.asks) else book()
        qty, px = _match(o.side, o.remaining_quantity, q.ltp, limit, bids, asks)
    if qty <= 0:
        if triggered:
            notify.order_event(db, o, "ORDER_TRIGGERED", f"at {notify.money(q.ltp)} · now a limit order at {notify.money(limit)}")
            db.commit()
            return f"order {o.id} TRIGGERED"
        if activated:
            notify.order_event(db, o, "ORDER_OPEN", f"limit {notify.money(limit)}")
            db.commit()
            return f"order {o.id} OPEN"
        return None
    if market_like:
        px = slip(o.side, px, slippage_pct(db, o.account_id))
    return _fill(db, o.id, o.filled_quantity, qty, px)


def process_price(db: Session, instrument_id: int, price: Decimal, at: datetime | None = None,
                  quote: "pricing.ExecQuote | None" = None) -> list[str]:
    """Apply one observed in-session price to the instrument's working orders and open positions. Returns event descriptions.

    `price` must be a fresh price of the current session (a websocket tick, or pricing.execution_quote); `at` is when it traded.
    Nothing happens while the exchange is closed. Gaps: fills happen at the observed price, which may be worse than a stop level."""
    at = ms.utc(at) if at is not None else ms.now()
    if not switches.get("engine_enabled"):
        return []                                              # paused from the developer console
    inst = db.get(Instrument, instrument_id)
    if inst is None or not ms.is_open(inst.exchange, at):
        return []
    q = quote or pricing.ExecQuote(Decimal(str(price)), at, "tick")
    price = q.ltp
    book = _book(inst, at)
    events: list[str] = []
    ids = db.scalars(select(Order.id).where(Order.instrument_id == instrument_id, Order.status.in_(WORKING))
                     .order_by(Order.id)).all()
    for oid in ids:
        try:
            ev = _evaluate(db, oid, inst, q, at, book)
        except Exception:  # noqa: BLE001  (one broken order must not stop the others)
            db.rollback()
            log.exception("order %s evaluation failed", oid)
            continue
        if ev:
            events.append(ev)
    with lock:
        for p in db.scalars(select(Position).where(Position.instrument_id == instrument_id, Position.status == "OPEN")).all():
            long_ = p.side == "BUY"
            reason = None
            if p.stop_loss is not None and ((long_ and price <= p.stop_loss) or (not long_ and price >= p.stop_loss)):
                reason = "STOP_LOSS"
            elif p.target is not None and ((long_ and price >= p.target) or (not long_ and price <= p.target)):
                reason = "TARGET"
            if reason:
                try:
                    px = slip("SELL" if long_ else "BUY", price, slippage_pct(db, p.account_id)) if reason == "STOP_LOSS" else price
                    exit_position(db, p, None, px, reason)
                    events.append(f"position {p.id} closed by {reason} @ {price}")
                except TradingError as e:
                    log.warning("Auto exit skipped for position %s: %s", p.id, e)
    return events


# ---------------------------------------------------------------------------------------------------------------- cancel / expire
def cancel_order(db: Session, order: Order) -> Order:
    with lock:
        if not db.execute(update(Order).where(Order.id == order.id, Order.status.in_(WORKING))
                          .values(status="CANCELLED", reject_reason="Cancelled by you", updated_at=ms.now())
                          .execution_options(synchronize_session=False)).rowcount:
            db.rollback()
            raise TradingError("Only open or pending orders can be cancelled")
        o = _reload(db, order.id)
        notify.order_event(db, o, "ORDER_CANCELLED", f"{o.filled_quantity} of {o.quantity} had executed" if o.filled_quantity else "")
        db.commit()
        return o


def expire_orders(db: Session, now: datetime | None = None) -> int:
    """DAY orders still working when their session has ended become EXPIRED. GTT orders (no expires_at) are untouched."""
    now = ms.utc(now) if now is not None else ms.now()     # SQLite keeps naive UTC: compare in UTC, never in IST
    n = 0
    with lock:
        ids = db.scalars(select(Order.id).where(Order.status.in_(WORKING), Order.expires_at.is_not(None),
                                                Order.expires_at <= now)).all()
        for oid in ids:
            o = _reload(db, oid)
            if o.status not in WORKING or not _cas(db, oid, o.status, "EXPIRED", reject_reason="Day order expired at market close"):
                db.rollback()
                continue
            o = _reload(db, oid)
            notify.order_event(db, o, "ORDER_EXPIRED", f"unfilled at the close · {o.filled_quantity} of {o.quantity} had executed"
                               if o.filled_quantity else "unfilled at the market close")
            db.commit()
            n += 1
    return n


# ---------------------------------------------------------------------------------------------------------------- positions
def settle_expiring_positions(db: Session) -> list[str]:
    """On expiry day in the last 5 minutes of the session, close open F&O positions at the latest traded price (reason EXPIRY).
    This is an approximation: real expiry settlement uses an official settlement price this app does not have."""
    now = ms.now().astimezone(pricing.IST)
    events = []
    rows = db.execute(select(Position, Instrument).join(Instrument, Instrument.id == Position.instrument_id)
                      .where(Position.status == "OPEN", Instrument.expiry == now.date())).all()
    for pos, inst in rows:
        close = pricing.session_hours(inst.exchange, now.date())[1]
        if now.hour * 60 + now.minute < close.hour * 60 + close.minute - 5 or not ms.is_open(inst.exchange, now):
            continue
        try:
            quote = pricing.execution_quote(inst, now)
            exit_position(db, pos, None, quote.ltp, "EXPIRY")
            events.append(f"position {pos.id} settled at expiry @ {quote.ltp}")
        except (pricing.PriceUnavailable, TradingError) as e:
            log.warning("Expiry settlement skipped for position %s: %s", pos.id, e)
    return events


def exit_position(db: Session, pos: Position, quantity: int | None, price: Decimal, reason: str = "MANUAL", *,
                  order_id: int | None = None, ledger_key: str | None = None, commit: bool = True) -> Trade:
    """Close `quantity` (all by default) of an open position at `price`. On failure the transaction is rolled back."""
    with lock:
        pos = db.get(Position, pos.id)
        db.refresh(pos)
        if pos.status != "OPEN":
            db.rollback()
            raise TradingError("Position is already closed")
        qty = quantity or pos.quantity
        if qty <= 0 or qty > pos.quantity:
            db.rollback()
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
        exit_charges = estimate_charges(pos.product, exit_leg, proceeds, inst.instrument_type, inst.exchange)
        credit = released_cash + gross - exit_charges
        try:
            acct.post_entry(db, account, "POSITION_EXIT", credit, f"Exit {qty} {inst.symbol} @ {price} ({reason})", ledger_key)
        except acct.LedgerError as e:
            db.rollback()
            raise TradingError(str(e))
        now = ms.now()
        total_charges = entry_share + exit_charges
        trade = Trade(account_id=pos.account_id, position_id=pos.id, instrument_id=pos.instrument_id, order_id=order_id, side=pos.side,
                      quantity=qty, entry_price=(released / qty).quantize(Decimal("0.0001")), exit_price=price,
                      gross_pnl=gross, charges=total_charges, net_pnl=gross - total_charges, exit_reason=reason,
                      strategy_id=pos.strategy_id, entry_time=pos.opened_at, exit_time=now)
        db.add(trade)
        db.add(TradeLog(account_id=pos.account_id, order_id=order_id, position_id=pos.id, instrument_id=pos.instrument_id, event="EXIT",
                        side=exit_leg, quantity=qty, price=price, charges=total_charges, reason=reason, ts=now))
        pos.quantity -= qty
        pos.invested_amount -= released_cash
        pos.entry_value -= released
        pos.entry_charges -= entry_share
        if last:
            pos.status, pos.closed_at = "CLOSED", now
        if commit:
            db.commit()
        else:
            db.flush()
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
