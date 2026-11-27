from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import owned_account
from app.api.trading import open_notional, position_out, trade_out
from app.database.session import get_db
from app.models import Order, Position, Trade, TradingAccount
from app.services import accounts as svc
from app.trading.engine import _ist_day_start as day_start_utc

router = APIRouter(prefix="/api/accounts", tags=["dashboard"])


@router.get("/{account_id}/dashboard")
def dashboard(acc: TradingAccount = Depends(owned_account), db: Session = Depends(get_db)):
    """Everything is computed from DB rows (ledger, positions, trades). Unrealized P&L needs live prices."""
    balance = svc.get_balance(db, acc.id)
    invested = open_notional(db, acc.id)
    positions = db.scalars(select(Position).where(Position.account_id == acc.id, Position.status == "OPEN")
                           .order_by(Position.id.desc())).all()
    pos_rows = [position_out(db, p) for p in positions]
    prices_ok = all(r["unrealized_pnl"] is not None for r in pos_rows)
    unrealized = sum((Decimal(r["unrealized_pnl"]) for r in pos_rows if r["unrealized_pnl"] is not None), Decimal(0))

    realized = Decimal(str(db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(
        Trade.account_id == acc.id))))
    total_trades = db.scalar(select(func.count()).select_from(Trade).where(Trade.account_id == acc.id)) or 0
    wins = db.scalar(select(func.count()).select_from(Trade).where(Trade.account_id == acc.id,
                                                                    Trade.net_pnl > 0)) or 0
    total_pnl = realized + unrealized
    orders_today = db.scalar(select(func.count()).select_from(Order).where(
        Order.account_id == acc.id, Order.created_at >= day_start_utc())) or 0
    recent = db.scalars(select(Trade).where(Trade.account_id == acc.id).order_by(Trade.id.desc()).limit(8)).all()
    return {
        "account": {"id": acc.id, "name": acc.name},
        "capital": {
            "initial_capital": acc.initial_capital,
            "available_balance": balance,
            "blocked_funds": 0,
            "invested_amount": invested,
            "total_virtual_capital": balance + invested + unrealized,
        },
        "pnl": {"realized": realized, "unrealized": unrealized, "total": total_pnl,
                "return_pct": float(total_pnl / acc.initial_capital * 100) if acc.initial_capital else 0},
        "stats": {"open_positions": len(positions), "total_trades": total_trades,
                  "win_rate": float(Decimal(wins) / total_trades * 100) if total_trades else None,
                  "current_drawdown": 0, "daily_risk_used": 0},
        "recent_trades": [trade_out(db, t) for t in recent],
        "open_positions": pos_rows,
        "has_trades": total_trades > 0,
        "orders_today": orders_today,
        "prices_available": prices_ok,
    }
