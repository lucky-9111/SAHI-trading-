from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_account
from app.database.session import get_db
from app.models import Order, Position, Strategy, Trade, TradingAccount, User
from app.models.market import Instrument
from app.services import accounts as acct
from app.trading import engine, pricing
from app.live import runtime
from app.trading.charges import estimate_charges, q2, required_cash

router = APIRouter(prefix="/api/accounts/{account_id}", tags=["trading"])
strategies_router = APIRouter(prefix="/api/strategies", tags=["strategies"])

Price = Decimal | None


class OrderIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str = "NSE"
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "TRIGGER"] = "MARKET"
    validity: Literal["DAY", "GTT"] = "DAY"
    product: Literal["INTRADAY", "DELIVERY", "SWING", "NRML"] = "INTRADAY"
    quantity: int | None = Field(default=None, gt=0, le=10_000_000)
    limit_price: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    stop_loss: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    target: Price = Field(default=None, gt=0, le=Decimal("10000000"))
    strategy_id: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class ExitIn(BaseModel):
    quantity: int | None = Field(default=None, gt=0)


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


def order_out(db: Session, o: Order) -> dict:
    inst = db.get(Instrument, o.instrument_id)
    strat = db.get(Strategy, o.strategy_id) if o.strategy_id else None
    return {"id": o.id, "symbol": inst.symbol, "exchange": inst.exchange, "side": o.side, "order_type": o.order_type,
            "strategy": strat.name if strat else "Manual", **chart_target(inst),
            "validity": o.validity, "expires_at": o.expires_at, "product": o.product, "quantity": o.quantity, "limit_price": s(o.limit_price),
            "stop_loss": s(o.stop_loss), "target": s(o.target), "status": o.status, "exec_price": s(o.exec_price),
            "reject_reason": o.reject_reason, "created_at": o.created_at, "executed_at": o.executed_at}


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
    return {"id": p.id, "symbol": inst.symbol, "exchange": inst.exchange, "side": p.side, "product": p.product,
            "instrument_type": inst.instrument_type, "lot_size": inst.lot_size, **chart_target(inst),
            "expiry": inst.expiry.isoformat() if inst.expiry else None,
            "quantity": p.quantity, "avg_price": s(avg), "current_price": s(cur),
            "invested_amount": s(p.invested_amount), "stop_loss": s(p.stop_loss), "target": s(p.target),
            "unrealized_pnl": s(upnl), "pnl_pct": s(pct), "strategy": strat.name if strat else "Manual",
            "opened_at": p.opened_at}


def trade_out(db: Session, t: Trade) -> dict:
    inst = db.get(Instrument, t.instrument_id)
    strat = db.get(Strategy, t.strategy_id) if t.strategy_id else None
    return {"id": t.id, "symbol": inst.symbol, **chart_target(inst), "side": t.side, "quantity": t.quantity, "entry_price": s(t.entry_price),
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
    if body.order_type in ("LIMIT", "TRIGGER"):
        entry = body.limit_price
        if entry is None:
            errors.append("Enter a trigger price" if body.order_type == "TRIGGER" else "Enter a limit price")
        elif body.order_type == "TRIGGER" and quote:
            if body.side == "BUY" and entry <= quote.price:
                errors.append("Trigger price must be above the current price for a BUY order")
            if body.side == "SELL" and entry >= quote.price:
                errors.append("Trigger price must be below the current price for a SELL order")
    else:
        entry = quote.price if quote else None
        if quote is None:
            errors.append(f"Market price unavailable: {price_err}")
    try:
        engine.validate_contract(inst, body.side, body.product, body.quantity or inst.lot_size)
    except engine.TradingError as e:
        errors.append(str(e))
    if entry is not None:
        errors += engine.validate_levels(body.side, entry, body.stop_loss, body.target)
    if quote and not quote.market_open:
        warnings.append("Market is closed. Market orders fill at the last available price.")

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

    out = {"ltp": s(quote.price) if quote else None, "market_open": quote.market_open if quote else None,
           "entry_price": s(entry), "suggested_quantity": suggested, "quantity": qty, "lot_size": lot,
           "instrument_type": itype,
           "risk_per_trade_pct": s(risk_pct), "max_risk_amount": s(risk_budget), "balance": s(balance),
           "errors": errors, "warnings": warnings}
    if entry is not None and qty:
        value = q2(entry * qty)
        cash = required_cash(itype, body.side, entry, qty, inst.strike)
        entry_ch = estimate_charges(body.product, body.side, value, itype, inst.exchange)
        out.update(order_value=s(value), entry_charges=s(entry_ch), required_funds=s(cash + entry_ch))
        if cash + entry_ch > balance:
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
                  product=body.product, quantity=body.quantity, limit_price=body.limit_price,
                  stop_loss=body.stop_loss, target=body.target, strategy_id=body.strategy_id,
                  idempotency_key=body.idempotency_key, validity=body.validity)
    runtime.notify_user(acc.user_id, {"type": "orders_changed", "events": [f"order {order.id} {order.status}"]})
    return order_out(db, order)


@router.get("/orders")
def list_orders(acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    rows = db.scalars(select(Order).where(Order.account_id == acc.id).order_by(Order.id.desc()).limit(500)).all()
    return [order_out(db, o) for o in rows]


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
    p = _own_position(db, acc, position_id)
    inst = db.get(Instrument, p.instrument_id)
    quote = _wrap(pricing.get_price, inst)
    out = trade_out(db, _wrap(engine.exit_position, db, p, body.quantity, quote.price, "MANUAL"))
    runtime.notify_user(acc.user_id, {"type": "orders_changed", "events": [f"position {position_id} exited"]})
    return out


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
    orders = db.scalars(select(Order).where(Order.account_id == acc.id, Order.status == "PENDING",
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
