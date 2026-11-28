"""Background execution worker (REST fallback). Every few seconds:
  * expires DAY orders whose session has ended (runs even while the market is closed);
  * for each instrument with working orders or open positions whose exchange is OPEN and which the live tick pipeline is not already
    serving, fetches a fresh in-session execution quote and lets the engine act on it (queued after-market orders, limits, stops,
    stop-loss / target exits). No fresh price -> nothing happens and the orders keep waiting.
All state lives in the database, so pending orders and open positions survive an application restart; the engine's compare-and-swap
fills make a re-run after a restart harmless."""
import logging
import threading

from sqlalchemy import select

from app.database.session import SessionLocal
from app.live import runtime
from app.models import Order, Position
from app.models.market import Instrument
from app.models.trading import WORKING_STATUSES
from app.admin import metrics
from app.trading import engine, market_status, pricing

log = logging.getLogger(__name__)
INTERVAL = 5


def tick() -> int:
    metrics.beat("execution_worker")
    with SessionLocal() as db:
        n = engine.expire_orders(db)
        if n:
            log.info("engine: %s day order(s) expired", n)
    processed = 0
    with SessionLocal() as db:
        ids = set(db.scalars(select(Order.instrument_id).where(Order.status.in_(WORKING_STATUSES))).all())
        ids |= set(db.scalars(select(Position.instrument_id).where(Position.status == "OPEN")).all())
        for iid in ids:
            inst = db.get(Instrument, iid)
            if inst is None or not market_status.is_open(inst.exchange):
                continue
            if runtime.fresh_tick(inst.exchange, inst.token, max_age=10.0) is not None:
                continue  # the live pipeline is handling this instrument from pushed ticks
            try:
                quote = pricing.execution_quote(inst)
            except pricing.PriceUnavailable as e:
                log.debug("engine: no fresh price for %s: %s", inst.symbol, e)
                continue
            for ev in engine.process_price(db, iid, quote.ltp, at=market_status.now(), quote=quote):
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
                log.exception("execution worker error")

    t = threading.Thread(target=loop, daemon=True, name="execution-worker")
    t.start()
    return t
