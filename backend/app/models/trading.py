from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.core import utcnow


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key"),
        Index("ix_orders_account_status", "account_id", "status"),
        CheckConstraint("quantity > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(4))  # BUY / SELL
    order_type: Mapped[str] = mapped_column(String(7))  # MARKET / LIMIT / TRIGGER (limit_price holds the trigger price)
    product: Mapped[str] = mapped_column(String(10))  # INTRADAY / DELIVERY
    quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    target: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="PENDING")  # PENDING EXECUTING EXECUTED CANCELLED REJECTED
    exec_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    validity: Mapped[str] = mapped_column(String(3), default="DAY")  # DAY expires at session close; GTT stays until filled/cancelled
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Position(Base):
    """Open (or closed) intraday/delivery position. `invested_amount` is exact: sum of fill notionals."""

    __tablename__ = "positions"
    __table_args__ = (Index("ix_positions_account_status", "account_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(4))  # BUY = long, SELL = short
    product: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    invested_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # cash locked (full value, or margin for F&O)
    entry_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))  # contract value at entry (P&L basis)
    entry_charges: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    target: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(6), default="OPEN")  # OPEN / CLOSED
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Trade(Base):
    """One completed exit (full or partial) of a position."""

    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_account_exit", "account_id", "exit_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"))
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(4))  # side of the position that was closed
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    exit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    exit_reason: Mapped[str] = mapped_column(String(20))  # MANUAL / STOP_LOSS / TARGET
    strategy_id: Mapped[int | None] = mapped_column(ForeignKey("strategies.id"), nullable=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
