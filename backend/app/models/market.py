from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class Instrument(Base):
    """Tradable instrument master. instrument_type is EQ now; FUT/OPT can be added later without schema change."""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", "instrument_type"),
        Index("ix_instruments_symbol", "symbol"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    exchange: Mapped[str] = mapped_column(String(10))
    symbol: Mapped[str] = mapped_column(String(50))  # e.g. RELIANCE
    trading_symbol: Mapped[str] = mapped_column(String(60))  # e.g. RELIANCE-EQ
    token: Mapped[str] = mapped_column(String(20))  # provider symbol token
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # company name (not in scrip master)
    instrument_type: Mapped[str] = mapped_column(String(10), default="EQ")  # EQ / FUT / OPT
    # Derivatives only
    underlying: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)  # CE / PE
    lot_size: Mapped[int] = mapped_column(default=1)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.05"))
