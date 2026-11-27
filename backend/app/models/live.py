"""Tables of the live market-data pipeline: closed candles, the editable market calendar and the fill / exit log."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models.core import utcnow


class LiveCandle(Base):
    """A CLOSED candle built from broker ticks (source 'live') or backfilled from the historical API (source 'hist'). Times are UTC."""

    __tablename__ = "live_candles"
    __table_args__ = (UniqueConstraint("token", "tf", "ts"), Index("ix_live_candles_lookup", "token", "tf", "ts"))
    id: Mapped[int] = mapped_column(primary_key=True)
    exchange: Mapped[str] = mapped_column(String(10))
    token: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(60))
    tf: Mapped[str] = mapped_column(String(4))  # 1m 5m 15m 1d
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # candle start, UTC
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    source: Mapped[str] = mapped_column(String(5), default="live")


class MarketCalendarRow(Base):
    """Exchange holiday / special session / late open, edited without code changes (see app.live.calendar)."""

    __tablename__ = "market_calendar"
    __table_args__ = (UniqueConstraint("date", "exchange"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (IST)
    exchange: Mapped[str] = mapped_column(String(4))  # NSE (also NFO) / BSE / MCX
    kind: Mapped[str] = mapped_column(String(10))  # holiday | special | late_open
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM
    end_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")


class TradeLog(Base):
    """Every paper fill and exit with its reason, written in the same transaction as the fill / exit itself."""

    __tablename__ = "trade_log"
    __table_args__ = (Index("ix_trade_log_account_ts", "account_id", "ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    account_id: Mapped[int] = mapped_column(Integer)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instrument_id: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(5))  # FILL (entry) | EXIT
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reason: Mapped[str] = mapped_column(String(20))  # ENTRY SIGNAL STOP_LOSS TARGET MANUAL EOD EXPIRY
    charges: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
