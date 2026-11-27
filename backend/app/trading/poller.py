"""Backend-controlled price loop: evaluates limit orders, stop-losses and targets while the market is open.
State lives in the DB, so pending orders and open positions survive an application restart."""
import logging
import threading

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models import Order, Position
from app.models.market import Instrument
from app.live import runtime
from app.trading import engine, pricing

log = logging.getLogger(__name__)
INTERVAL = 5


def tick() -> int:
    with SessionLocal() as db:
        n = engine.expire_orders(db)  # runs even when the market is closed
        if n:
            log.info("engine: %s day order(s) expired", n)
    processed = 0
    with SessionLocal() as db:
        ids = set(db.scalars(select(Order.instrument_id).where(Order.status == "PENDING")).all())
        ids |= set(db.scalars(select(Position.instrument_id).where(Position.status == "OPEN")).all())
        for iid in ids:
            inst = db.get(Instrument, iid)
            if not pricing.is_market_open(exchange=inst.exchange):
                continue
            if runtime.fresh_tick(inst.exchange, inst.token, max_age=10.0) is not None:
                continue  # the live pipeline is handling this instrument from pushed ticks
            try:
                quote = pricing.get_price(inst, max_age=0)
            except pricing.PriceUnavailable:
                continue
            for ev in engine.process_price(db, iid, quote.price):
                log.info("engine: %s (%s)", ev, inst.symbol)
            processed += 1
        for ev in engine.settle_expiring_positions(db):
            log.info("engine: %s", ev)
    return processed


def start(stop: threading.Event) -> threading.Thread:
    def loop():
        while not stop.wait(INTERVAL):
            try:
                tick()
            except Exception:
                log.exception("price loop error")

    t = threading.Thread(target=loop, daemon=True, name="price-loop")
    t.start()
    return t
