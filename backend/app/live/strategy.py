"""Strategy interface. A strategy sees only CLOSED candles and answers with a Signal; it never talks to the broker or the engine.

    class MyStrategy(Strategy):
        def on_candle(self, symbol, tf, candle, history): ...
            return Signal("BUY", entry=candle.close, stop=candle.low, target=candle.close * 1.01, reason="breakout")

The StrategyRunner turns a Signal into a paper order (MARKET entry with the stop and target attached). The order's idempotency key is built from
strategy + instrument + timeframe + candle time, so replaying the same candle (a restart, a backfill) can never place the same order twice.
"""
from __future__ import annotations

import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from app.database.session import SessionLocal
from app.live.candles import Candle
from app.models import TradingAccount
from app.models.market import Instrument

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Signal:
    side: str                 # BUY | SELL
    entry: float              # reference price (the order itself is a MARKET order)
    stop: float | None
    target: float | None
    reason: str = ""


class Strategy(ABC):
    name = "strategy"

    @abstractmethod
    def on_candle(self, symbol: str, tf: str, candle: Candle, history: list[Candle]) -> Signal | None: ...


@dataclass
class Binding:
    """Run `strategy` on `tf` candles of one instrument for one paper account.

    `underlying` binds to the FRONT-MONTH future of that underlying (futures rollover): `resolve()` picks the contract again every day and after
    the contract's expiry, so the subscription moves to next month's contract by itself. Without `underlying`, `symbol` is a fixed instrument."""

    strategy: Strategy
    account_id: int
    exchange: str
    tf: str = "5m"
    symbol: str | None = None
    underlying: str | None = None
    lots: int = 1
    product: str = "INTRADAY"
    current: tuple[str, str, str, int] | None = None     # (exchange, token, symbol, lot_size) of the instrument now followed

    def resolve(self, now: dt.datetime, db=None) -> tuple[str, str, str, int] | None:
        own = db is None
        db = db or SessionLocal()
        try:
            if self.underlying:
                inst = front_month(db, self.underlying, self.exchange, now)
            else:
                inst = db.scalar(select(Instrument).where(Instrument.exchange == self.exchange, Instrument.symbol == self.symbol))
            self.current = (inst.exchange, inst.token, inst.symbol, inst.lot_size) if inst else None
            return self.current
        finally:
            if own:
                db.close()


def front_month(db, underlying: str, exchange: str, now: dt.datetime) -> Instrument | None:
    """Nearest future of `underlying` that has not expired. On its expiry day it stays the front month until that exchange's session ends."""
    from app.live import calendar

    n = now.astimezone(calendar.IST)
    futs = db.scalars(select(Instrument).where(Instrument.exchange == exchange, Instrument.instrument_type == "FUT",
                                               Instrument.underlying == underlying.upper(), Instrument.expiry >= n.date())
                      .order_by(Instrument.expiry)).all()
    for f in futs:
        if f.expiry == n.date():
            b = calendar.session_bounds(exchange, f.expiry)
            if b and now.astimezone(calendar.UTC) >= b[1]:
                continue                                  # expired for good once its last session has ended
        return f
    return None


class StrategyRunner:
    def __init__(self, history) -> None:
        self.bindings: list[Binding] = []
        self.history = history
        self.signals = 0
        self.errors = 0

    def add(self, b: Binding) -> None:
        self.bindings.append(b)

    def refresh(self, now: dt.datetime) -> set[tuple[str, str]]:
        """Re-resolve every binding (rollover) and return the tokens the strategies need subscribed."""
        out: set[tuple[str, str]] = set()
        for b in self.bindings:
            cur = b.resolve(now)
            if cur:
                out.add((cur[0], cur[1]))
        return out

    def on_candle(self, c: Candle) -> list[tuple[Binding, Signal, Candle]]:
        out = []
        for b in self.bindings:
            if not b.current or b.tf != c.tf or (b.current[0], b.current[1]) != (c.exchange, c.token):
                continue
            hist = self.history.data.get((f"{c.exchange}:{c.token}", c.tf), [])
            try:
                sig = b.strategy.on_candle(c.symbol, c.tf, c, hist)
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("strategy %s failed on %s %s", b.strategy.name, c.symbol, c.tf)
                continue
            if sig:
                self.signals += 1
                out.append((b, sig, c))
        return out


def place_signal(b: Binding, sig: Signal, c: Candle, session_factory=SessionLocal) -> str:
    """Signal -> paper order (sync, DB). Returns the order status, or the reason it was refused."""
    from app.trading import engine

    key = f"sig-{b.strategy.name}-{c.exchange}{c.token}-{c.tf}-{int(c.start.timestamp())}"[:64]
    with session_factory() as db:
        acc = db.get(TradingAccount, b.account_id)
        inst = db.scalar(select(Instrument).where(Instrument.exchange == c.exchange, Instrument.token == c.token))
        if not acc or not inst:
            return "unknown account or instrument"
        try:
            o = engine.place_order(db, acc, inst, side=sig.side, order_type="MARKET", product=b.product, quantity=b.lots * inst.lot_size,
                                   limit_price=None, stop_loss=Decimal(str(round(sig.stop, 2))) if sig.stop else None,
                                   target=Decimal(str(round(sig.target, 2))) if sig.target else None, strategy_id=None, idempotency_key=key)
        except Exception as e:  # noqa: BLE001  (TradingError, PriceUnavailable ...)
            log.warning("signal refused (%s %s): %s", b.strategy.name, inst.symbol, e)
            return str(e)
        return o.status      # EXECUTED / PENDING / REJECTED; a repeated key returns the order that already exists
