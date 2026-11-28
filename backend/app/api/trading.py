from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_account
from app.database.session import get_db
from app.models import Notification, Order, Position, Strategy, Trade, TradingAccount, User
from app.models.live import TradeLog
from app.models.market import Instrument
from app.models.trading import WORKING_STATUSES
from app.services import accounts as acct
from app.trading import engine, market_status, pricing
from app.live import runtime
from app.trading.charges import estimate_charges, q2, required_cash

router = APIRouter(prefix="/api/accounts/{account_id}", tags=["trading"])
strategies_router = APIRouter(prefix="/api/strategies", tags=["strategies"])

Price = Decimal | None


class OrderIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str = "NSE"
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M", "TRIGGER"] = "MARKET"   # TRIGGER = legacy name of SL-M
    validity: Literal["DAY", "GTT"] = "DAY"
    product: Literal["INTRADAY", "DELIVERY", "SWING", "NRML"] = "INTRADAY"
    quantity: int | None = Field(default=None, gt=0, le=10_000_000)
    limit_price: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    trigger_price: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    stop_loss: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    target: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    strategy_id: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class ExitIn(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    idempotency_key: str | None = Field(default=None, max_length=64)


class OrderSettingsIn(BaseModel):
    after_hours_mode: Literal["QUEUE", "REJECT"]
    slippage_pct: Decimal | None = Field(default=None, ge=0, le=5)


class ModifyIn(BaseModel):
    stop_loss: Price = Field(default=None, gt=0)
    target: Price = Field(default=None, gt=0)
    clear_stop_loss: bool = False
    clear_target: bool = False


class RiskIn(BaseModel):
    risk_per_trade_pct: Decimal = Field(gt=0, le=100)
    max_daily_loss: Decimal | None = Field(default=None, gt=0)
    max_weekly_loss: Decimal | None = Field(default=None, gt=0)
    max_open_positions: int = Field(ge=1, le=500)
    strict_protection: bool = False


def s(x) -> str | None:
    """Serialize money for the API as a 2-decimal string (display only; storage stays exact Decimal)."""
    if x is None:
        return None
    return str(q2(x)) if isinstance(x, Decimal) else str(x)


def _instrument(db: Session, symbol: str, exchange: str) -> Instrument:
    """Equity (NSE) or a derivative contract (NFO) by exchange + symbol."""
    inst = db.scalar(select(Instrument).where(Instrument.exchange == exchange.upper(),
                                              Instrument.symbol == symbol.upper()))
    if not inst:
        raise HTTPException(404, "Unknown instrument")
    return inst


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except engine.TradingError as e:
        raise HTTPException(400, str(e))
    except pricing.PriceUnavailable as e:
        raise HTTPException(503, f"No market price available: {e}")


def open_notional(db: Session, account_id: int) -> Decimal:
    v = db.scalar(select(func.coalesce(func.sum(Position.invested_amount), 0)).where(
        Position.account_id == account_id, Position.status == "OPEN"))
    return Decimal(str(v))


def chart_target(inst: Instrument) -> dict:
    """Where the 'Chart' button should open: the stock itself, or the underlying for an F&O contract."""
    if inst.instrument_type == "EQ":
        return {"chart_symbol": inst.symbol, "chart_exchange": inst.exchange}
    if inst.exchange == "MCX":      # commodities have no spot index: chart the contract itself
        return {"chart_symbol": inst.symbol, "chart_exchange": "MCX"}
    return {"chart_symbol": inst.underlying or inst.symbol, "chart_exchange": "NSE"}


ORDER_GROUPS = {"open": ("OPEN", "TRIGGER_PENDING", "PARTIALLY_FILLED"), "pending": ("PENDING",), "executed": ("FILLED",),
                "rejected": ("REJECTED",), "cancelled": ("CANCELLED", "EXPIRED"), "working": WORKING_STATUSES}


def order_out(db: Session, o: Order) -> dict:
    inst = db.get(Instrument, o.instrument_id)
    strat = db.get(Strategy, o.strategy_id) if o.strategy_id else None
    utc = market_status.utc
    return {"id": o.id, "symbol": inst.symbol, "exchange": inst.exchange, "side": o.side, "order_type": o.order_type,
            "strategy": strat.name if strat else "Manual", **chart_target(inst),
            "validity": o.validity, "expires_at": utc(o.expires_at), "product": o.product, "quantity": o.quantity,
            "filled_quantity": o.filled_quantity or 0, "remaining_quantity": o.remaining_quantity,
            "limit_price": s(o.limit_price), "trigger_price": s(o.trigger_price),
            "stop_loss": s(o.stop_loss), "target": s(o.target), "status": o.status,
            "exec_price": s(o.exec_price), "avg_price": s(o.exec_price), "reject_reason": o.reject_reason,
            "after_market": bool(o.after_market), "reduce_only": bool(o.reduce_only), "cancellable": o.status in WORKING_STATUSES,
            "created_at": utc(o.created_at), "triggered_at": utc(o.triggered_at), "executed_at": utc(o.executed_at),
            "updated_at": utc(o.updated_at)}


def position_out(db: Session, p: Position, with_price: bool = True) -> dict:
    inst = db.get(Instrument, p.instrument_id)
    cur = upnl = None
    if with_price and p.status == "OPEN":
        try:
            cur = pricing.get_price(inst).price
            value = q2(cur * p.quantity)
            upnl = value - p.entry_value if p.side == "BUY" else p.entry_value - value
        except pricing.PriceUnavailable:
            pass
    avg = (p.entry_value / p.quantity).quantize(Decimal("0.01")) if p.quantity else None
    pct = (upnl / p.invested_amount * 100).quantize(Decimal("0.01")) if upnl is not None and p.invested_amount else None
    strat = db.get(Strategy, p.strategy_id) if p.strategy_id else None
    return {"id": p.id, "symbol": inst.symbol, "exchange": inst.exchange, "token": inst.token, "entry_value": s(p.entry_value),
            "side": p.side, "product": p.product,
            "instrument_type": inst.instrument_type, "lot_size": inst.lot_size, **chart_target(inst),
            "expiry": inst.expiry.isoformat() if inst.expiry else None,
            "quantity": p.quantity, "avg_price": s(avg), "current_price": s(cur),
            "invested_amount": s(p.invested_amount), "stop_loss": s(p.stop_loss), "target": s(p.target),
            "unrealized_pnl": s(upnl), "pnl_pct": s(pct), "strategy": strat.name if strat else "Manual",
            "opened_at": p.opened_at}


def trade_out(db: Session, t: Trade) -> dict:
    inst = db.get(Instrument, t.instrument_id)
    strat = db.get(Strategy, t.strategy_id) if t.strategy_id else None
    return {"id": t.id, "order_id": t.order_id, "symbol": inst.symbol, **chart_target(inst), "side": t.side, "quantity": t.quantity, "entry_price": s(t.entry_price),
            "exit_price": s(t.exit_price), "gross_pnl": s(t.gross_pnl), "charges": s(t.charges),
            "net_pnl": s(t.net_pnl), "exit_reason": t.exit_reason, "strategy": strat.name if strat else "Manual",
            "entry_time": t.entry_time, "exit_time": t.exit_time}


# ---------- preview / calculator ----------
@router.post("/orders/preview")
def preview(body: OrderIn, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    """Live calculator. Validation problems are returned in `errors` (not as HTTP errors) so the UI can show them."""
    inst = _instrument(db, body.symbol, body.exchange)
    errors: list[str] = []
    warnings: list[str] = []
    quote = None
    try:
        quote = pricing.get_price(inst)
    except pricing.PriceUnavailable as e:
        price_err = str(e)
    otype, trig = body.order_type, body.trigger_price
    if otype == "TRIGGER":
        otype, trig = "SL-M", trig or body.limit_price
    if otype in ("LIMIT", "SL", "SL-M"):
        entry = body.limit_price if otype in ("LIMIT", "SL") else trig
        if otype in ("LIMIT", "SL") and body.limit_price is None:
            errors.append("Enter a limit price")
        if otype in ("SL", "SL-M") and trig is None:
            errors.append("Enter a trigger price")
        elif otype in ("SL", "SL-M") and quote:
            if body.side == "BUY" and trig <= quote.price:
                errors.append("Trigger price must be above the current price for a BUY order")
            if body.side == "SELL" and trig >= quote.price:
                errors.append("Trigger price must be below the current price for a SELL order")
        if otype == "SL" and trig is not None and body.limit_price is not None:
            if body.side == "BUY" and body.limit_price < trig:
                errors.append("For a BUY stop-loss order the limit price must be at or above the trigger price")
            if body.side == "SELL" and body.limit_price > trig:
                errors.append("For a SELL stop-loss order the limit price must be at or below the trigger price")
    else:
        entry = quote.price if quote else None
        if quote is None:
            errors.append(f"Market price unavailable: {price_err}")
    held = engine.open_position(db, acc.id, inst.id, body.product)
    reducing = held is not None and held.side != body.side
    try:
        engine.validate_contract(inst, body.side, body.product, body.quantity or inst.lot_size, reducing=reducing)
    except engine.TradingError as e:
        errors.append(str(e))
    if reducing:
        warnings.append(f"This order exits your open {held.side.lower()} position of {held.quantity}.")
        if (body.quantity or 0) > held.quantity:
            errors.append(f"Exit quantity cannot exceed the open position ({held.quantity})")
    elif entry is not None:
        errors += engine.validate_levels(body.side, entry, body.stop_loss, body.target)
    mstat = market_status.status(inst.exchange)
    mode = acc.risk.after_hours_mode or "QUEUE"
    if not mstat.is_open:
        if mode == "REJECT" and body.validity == "DAY":
            errors.append(f"{mstat.label}. After-market orders are off (Settings), so this order would be rejected.")
        else:
            nxt = market_status.utc(mstat.next_open)
            when = nxt.astimezone(pricing.IST).strftime("%a %d %b, %H:%M") if nxt else "the next session"
            warnings.append(f"{mstat.label}. The order will be queued and executes only at a fresh live price after the open ({when} IST).")

    balance = acct.get_balance(db, acc.id)
    equity = balance + open_notional(db, acc.id)
    risk_pct = acc.risk.risk_per_trade_pct
    risk_budget = q2(equity * risk_pct / 100)
    per_share = abs(entry - body.stop_loss) if entry is not None and body.stop_loss is not None else None
    lot = inst.lot_size or 1
    suggested = None
    if per_share:
        lots = int((risk_budget / (per_share * lot)).to_integral_value(rounding=ROUND_FLOOR))
        suggested = lots * lot  # whole lots only
    qty = body.quantity or suggested or 0
    itype = inst.instrument_type
    if itype != "EQ":
        warnings.append("F&O margin is an approximate fixed percentage, not exchange SPAN margin.")

    out = {"ltp": s(quote.price) if quote else None, "market_open": mstat.is_open, "market": mstat.as_dict(),
           "after_hours_mode": mode,
           "entry_price": s(entry), "suggested_quantity": suggested, "quantity": qty, "lot_size": lot,
           "instrument_type": itype,
           "risk_per_trade_pct": s(risk_pct), "max_risk_amount": s(risk_budget), "balance": s(balance),
           "errors": errors, "warnings": warnings}
    if entry is not None and qty:
        value = q2(entry * qty)
        cash = required_cash(itype, body.side, entry, qty, inst.strike)
        entry_ch = estimate_charges(body.product, body.side, value, itype, inst.exchange)
        out.update(order_value=s(value), entry_charges=s(entry_ch), required_funds=s(cash + entry_ch))
        if cash + entry_ch > balance and not reducing:
            errors.append("Insufficient virtual funds for this order")
        if per_share:
            total_risk = q2(per_share * qty)
            out.update(risk_per_share=s(per_share), total_risk=s(total_risk))
            if total_risk > risk_budget:
                warnings.append(f"Risk ₹{total_risk} exceeds your {risk_pct}% per-trade budget (₹{risk_budget})")
        if body.target is not None:
            reward_ps = abs(body.target - entry)
            gross = q2(reward_ps * qty)
            exit_leg = "SELL" if body.side == "BUY" else "BUY"
            exit_ch = estimate_charges(body.product, exit_leg, q2(body.target * qty), itype, inst.exchange)
            out.update(reward_per_share=s(reward_ps), potential_reward=s(gross),
                       estimated_net_reward=s(gross - entry_ch - exit_ch))
            if per_share:
                out["risk_reward"] = s((reward_ps / per_share).quantize(Decimal("0.01")))
    return out


# ---------- orders ----------
@router.post("/orders", status_code=201)
def create_order(body: OrderIn, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    if not body.quantity:
        raise HTTPException(422, "Quantity is required")
    inst = _instrument(db, body.symbol, body.exchange)
    order = _wrap(engine.place_order, db, acc, inst, side=body.side, order_type=body.order_type,
                  product=body.product, quantity=body.quantity, limit_price=body.limit_price, trigger_price=body.trigger_price,
                  stop_loss=body.stop_loss, target=body.target, strategy_id=body.strategy_id,
                  idempotency_key=body.idempotency_key, validity=body.validity)
    runtime.notify_user(acc.user_id, {"type": "orders_changed", "events": [f"order {order.id} {order.status}"]})
    return order_out(db, order)


@router.get("/orders")
def list_orders(status: Literal["all", "open", "pending", "executed", "rejected", "cancelled", "working"] = "all",
                acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    q = select(Order).where(Order.account_id == acc.id)
    if status != "all":
        q = q.where(Order.status.in_(ORDER_GROUPS[status]))
    rows = db.scalars(q.order_by(Order.id.desc()).limit(500)).all()
    return [order_out(db, o) for o in rows]


@router.get("/orders/{order_id}")
def order_detail(order_id: int, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    """One order with its executions (each fill: time, quantity, price, charges) and its status history."""
    o = db.get(Order, order_id)
    if not o or o.account_id != acc.id:
        raise HTTPException(404, "Order not found")
    fills = db.scalars(select(TradeLog).where(TradeLog.order_id == o.id).order_by(TradeLog.id)).all()
    events = db.scalars(select(Notification).where(Notification.order_id == o.id, Notification.account_id == acc.id)
                        .order_by(Notification.id)).all()
    history = [{"at": market_status.utc(o.created_at), "kind": "ORDER_RECEIVED", "title": "Order received",
                "body": "after-market order" if o.after_market else ""}]
    history += [{"at": market_status.utc(n.created_at), "kind": n.kind, "title": n.title, "body": n.body} for n in events]
    return {**order_out(db, o),
            "fills": [{"at": market_status.utc(f.ts), "quantity": f.quantity, "price": s(f.price), "charges": s(f.charges),
                       "event": f.event, "reason": f.reason} for f in fills],
            "history": history}


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: int, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o or o.account_id != acc.id:
        raise HTTPException(404, "Order not found")
    out = order_out(db, _wrap(engine.cancel_order, db, o))
    runtime.notify_user(acc.user_id, {"type": "orders_changed", "events": [f"order {order_id} CANCELLED"]})
    return out


# ---------- positions ----------
def _own_position(db: Session, acc: TradingAccount, pid: int) -> Position:
    p = db.get(Position, pid)
    if not p or p.account_id != acc.id:
        raise HTTPException(404, "Position not found")
    return p


@router.get("/positions")
def list_positions(acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    rows = db.scalars(select(Position).where(Position.account_id == acc.id, Position.status == "OPEN")
                      .order_by(Position.id.desc())).all()
    return [position_out(db, p) for p in rows]


@router.post("/positions/{position_id}/exit")
def exit_pos(position_id: int, body: ExitIn, acc: TradingAccount = Depends(owned_account),
             db: Session = Depends(get_db)):
    """Exit through the order engine: a MARKET order on the opposite side. It executes now while the market is open (at a fresh
    price), and is queued (after-market order) or rejected per the account setting while it is closed. Never at a stale price."""
    p = _own_position(db, acc, position_id)
    if p.status != "OPEN":
        raise HTTPException(400, "Position is already closed")
    inst = db.get(Instrument, p.instrument_id)
    order = _wrap(engine.place_order, db, acc, inst, side="SELL" if p.side == "BUY" else "BUY", order_type="MARKET",
                  product=p.product, quantity=body.quantity or p.quantity, limit_price=None, stop_loss=None, target=None,
                  strategy_id=p.strategy_id, idempotency_key=body.idempotency_key, validity="DAY")
    trade = db.scalar(select(Trade).where(Trade.order_id == order.id).order_by(Trade.id.desc()))
    runtime.notify_user(acc.user_id, {"type": "orders_changed", "events": [f"order {order.id} {order.status}"]})
    return {"order": order_out(db, order), "trade": trade_out(db, trade) if trade else None}


@router.patch("/positions/{position_id}")
def modify_pos(position_id: int, body: ModifyIn, acc: TradingAccount = Depends(owned_account),
               db: Session = Depends(get_db)):
    p = _own_position(db, acc, position_id)
    quote = _wrap(pricing.get_price, db.get(Instrument, p.instrument_id))
    p = _wrap(engine.modify_position, db, p, body.stop_loss, body.target, body.clear_stop_loss,
              body.clear_target, quote.price)
    return position_out(db, p)


# ---------- trades ----------
@router.get("/trades")
def list_trades(acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    rows = db.scalars(select(Trade).where(Trade.account_id == acc.id).order_by(Trade.id.desc()).limit(1000)).all()
    return [trade_out(db, t) for t in rows]


# ---------- order settings ----------
def _order_settings(acc: TradingAccount) -> dict:
    r = acc.risk
    return {"after_hours_mode": r.after_hours_mode or "QUEUE", "slippage_pct": s(r.slippage_pct) if r.slippage_pct is not None else None,
            "default_slippage_pct": str(engine.slippage_pct()), "depth_fills": engine.get_settings().paper_depth_fills}


@router.get("/order-settings")
def get_order_settings(acc: TradingAccount = Depends(owned_account)):
    return _order_settings(acc)


@router.put("/order-settings")
def put_order_settings(body: OrderSettingsIn, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    acc.risk.after_hours_mode, acc.risk.slippage_pct = body.after_hours_mode, body.slippage_pct
    db.commit()
    return _order_settings(acc)


# ---------- risk settings ----------
@router.get("/risk")
def get_risk(acc: TradingAccount = Depends(owned_account)):
    r = acc.risk
    return {"risk_per_trade_pct": s(r.risk_per_trade_pct), "max_daily_loss": s(r.max_daily_loss),
            "max_weekly_loss": s(r.max_weekly_loss), "max_open_positions": r.max_open_positions,
            "strict_protection": r.strict_protection}


@router.put("/risk")
def put_risk(body: RiskIn, acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    r = acc.risk
    r.risk_per_trade_pct, r.max_daily_loss, r.max_weekly_loss = body.risk_per_trade_pct, body.max_daily_loss, body.max_weekly_loss
    r.max_open_positions, r.strict_protection = body.max_open_positions, body.strict_protection
    db.commit()
    return get_risk(acc)


@router.get("/symbol-context")
def symbol_context(symbol: str, exchange: str = "NSE", acc: TradingAccount = Depends(owned_account),
                   db: Session = Depends(get_db)):
    """What the user did in this symbol: open positions, pending orders and recent closed trades, each with the
    strategy chosen at entry. A symbol also matches F&O contracts whose underlying it is (e.g. NIFTY)."""
    sym = symbol.upper()
    ids = db.scalars(select(Instrument.id).where(
        ((Instrument.symbol == sym) & (Instrument.exchange == exchange.upper())) | (Instrument.underlying == sym))).all()
    if not ids:
        return {"positions": [], "orders": [], "trades": []}
    positions = db.scalars(select(Position).where(Position.account_id == acc.id, Position.status == "OPEN",
                                                  Position.instrument_id.in_(ids)).order_by(Position.id.desc())).all()
    orders = db.scalars(select(Order).where(Order.account_id == acc.id, Order.status.in_(WORKING_STATUSES),
                                            Order.instrument_id.in_(ids)).order_by(Order.id.desc())).all()
    trades = db.scalars(select(Trade).where(Trade.account_id == acc.id, Trade.instrument_id.in_(ids))
                        .order_by(Trade.id.desc()).limit(5)).all()
    return {"positions": [position_out(db, p) for p in positions], "orders": [order_out(db, o) for o in orders],
            "trades": [trade_out(db, t) for t in trades]}


@strategies_router.get("")
def list_strategies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    acct.ensure_default_strategies(db, user.id)  # existing users get new default strategies too
    rows = db.scalars(select(Strategy).where(Strategy.user_id == user.id).order_by(Strategy.id)).all()
    return [{"id": x.id, "name": x.name} for x in rows]
