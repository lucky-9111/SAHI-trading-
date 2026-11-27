"""Phase 1 models. Money is stored as Numeric(18,2) and handled as Decimal."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accounts: Mapped[list["TradingAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class TradingAccount(Base):
    """An independent virtual portfolio. Balance is derived from the ledger, never edited directly."""

    __tablename__ = "trading_accounts"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="accounts")
    risk: Mapped["RiskSettings"] = relationship(back_populates="account", uselist=False, cascade="all, delete-orphan")


class LedgerEntry(Base):
    """Append-only virtual funds ledger. amount > 0 credits, amount < 0 debits."""

    __tablename__ = "virtual_funds_ledger"
    __table_args__ = (
        Index("ix_ledger_account_created", "account_id", "created_at"),
        UniqueConstraint("account_id", "idempotency_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"))
    entry_type: Mapped[str] = mapped_column(String(30))  # INITIAL, DEPOSIT, WITHDRAWAL, RESET ...
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    description: Mapped[str] = mapped_column(String(255), default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RiskSettings(Base):
    __tablename__ = "risk_settings"
    __table_args__ = (CheckConstraint("risk_per_trade_pct > 0 AND risk_per_trade_pct <= 100"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("trading_accounts.id", ondelete="CASCADE"), unique=True)
    risk_per_trade_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("1.00"))
    max_daily_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_weekly_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=10)
    strict_protection: Mapped[bool] = mapped_column(Boolean, default=False)
    account: Mapped[TradingAccount] = relationship(back_populates="risk")


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    entry_rules: Mapped[str] = mapped_column(Text, default="")
    exit_rules: Mapped[str] = mapped_column(Text, default="")
    stop_loss_rules: Mapped[str] = mapped_column(Text, default="")
    target_rules: Mapped[str] = mapped_column(Text, default="")
    default_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplicationSetting(Base):
    __tablename__ = "application_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
