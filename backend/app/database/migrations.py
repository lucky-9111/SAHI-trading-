"""Idempotent data migrations, run at startup right after `ensure_columns()` adds the new columns.

Order management v2 (professional order lifecycle):
  * status EXECUTED                     -> FILLED (filled_quantity = quantity)
  * order type TRIGGER                  -> SL-M (its trigger moves from limit_price to trigger_price)
  * PENDING LIMIT orders                -> OPEN, PENDING SL / SL-M orders -> TRIGGER_PENDING
  * CANCELLED with "Day order expired"  -> EXPIRED
  * EXECUTING (a fill lock the old engine never committed) -> PENDING
Every statement only matches rows still in the old shape, so running it again changes nothing. Fills, positions, trades and the ledger
are not touched.
"""
import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

ORDER_V2 = [
    "UPDATE orders SET filled_quantity = 0 WHERE filled_quantity IS NULL",
    "UPDATE orders SET after_market = 0 WHERE after_market IS NULL",
    "UPDATE orders SET reduce_only = 0 WHERE reduce_only IS NULL",
    "UPDATE orders SET status = 'FILLED', filled_quantity = quantity WHERE status = 'EXECUTED'",
    "UPDATE orders SET order_type = 'SL-M', trigger_price = COALESCE(trigger_price, limit_price), limit_price = NULL "
    "WHERE order_type = 'TRIGGER'",
    "UPDATE orders SET status = 'PENDING' WHERE status = 'EXECUTING'",
    "UPDATE orders SET status = 'OPEN' WHERE status = 'PENDING' AND order_type = 'LIMIT' AND after_market = 0",
    "UPDATE orders SET status = 'TRIGGER_PENDING' WHERE status = 'PENDING' AND order_type IN ('SL', 'SL-M') AND after_market = 0",
    "UPDATE orders SET status = 'EXPIRED' WHERE status = 'CANCELLED' AND reject_reason = 'Day order expired'",
]


def run(engine) -> None:
    insp = inspect(engine)
    if not insp.has_table("orders"):
        return
    cols = {c["name"] for c in insp.get_columns("orders")}
    if not {"filled_quantity", "trigger_price", "after_market", "reduce_only"} <= cols:
        log.warning("orders table lacks the order-management columns; skipping the data migration")
        return
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":                       # SQLite does not enforce VARCHAR lengths
            conn.execute(text("ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(20)"))
        changed = 0
        for sql in ORDER_V2:
            changed += conn.execute(text(sql)).rowcount or 0
    if changed:
        log.info("order management migration: %s row update(s)", changed)
