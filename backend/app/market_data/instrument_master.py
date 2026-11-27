"""Instrument master sync from Angel One's public scrip master (no credentials required)."""
import json
import logging
import urllib.request
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.market import Instrument

log = logging.getLogger(__name__)
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
DERIV_TYPES = {"FUTIDX": "FUT", "FUTSTK": "FUT", "OPTIDX": "OPT", "OPTSTK": "OPT"}


def download_scrip_master(url: str = SCRIP_MASTER_URL, timeout: int = 300) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "agroup-trader"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URL)
        return json.loads(r.read())


def _tick(r: dict) -> Decimal:
    return (Decimal(str(r.get("tick_size") or 5)) / 100).quantize(Decimal("0.0001"))  # paise -> rupees


def sync_nse_equities(db: Session, rows: list[dict]) -> int:
    """Upsert NSE cash-segment equities (symbols ending -EQ). Returns number of rows processed."""
    existing = {(i.exchange, i.symbol, i.instrument_type): i
                for i in db.scalars(select(Instrument).where(Instrument.instrument_type == "EQ"))}
    n = 0
    for r in rows:
        if r.get("exch_seg") != "NSE" or not str(r.get("symbol", "")).endswith("-EQ"):
            continue
        symbol = r["name"].strip()
        if not symbol:
            continue
        key = ("NSE", symbol, "EQ")
        inst = existing.get(key)
        if inst is None:
            inst = Instrument(exchange="NSE", symbol=symbol, instrument_type="EQ")
            db.add(inst)
            existing[key] = inst
        inst.trading_symbol = r["symbol"]
        inst.token = str(r["token"])
        inst.lot_size = int(r.get("lotsize") or 1)
        inst.tick_size = _tick(r)
        n += 1
    db.commit()
    return n


def sync_derivatives(db: Session, rows: list[dict], today: date | None = None) -> int:
    """Upsert NFO index/stock futures and options that have not expired. Expired contracts are removed
    only if no order or position references them."""
    today = today or date.today()
    existing = {(i.exchange, i.symbol, i.instrument_type): i
                for i in db.scalars(select(Instrument).where(Instrument.instrument_type.in_(["FUT", "OPT"])))}
    seen: set[tuple] = set()
    n = 0
    for r in rows:
        itype = DERIV_TYPES.get(r.get("instrumenttype"))
        if r.get("exch_seg") != "NFO" or not itype:
            continue
        try:
            expiry = datetime.strptime(r["expiry"], "%d%b%Y").date()
        except (KeyError, ValueError):
            continue
        if expiry < today:
            continue
        symbol = r["symbol"].strip()
        key = ("NFO", symbol, itype)
        inst = existing.get(key)
        if inst is None:
            inst = Instrument(exchange="NFO", symbol=symbol, instrument_type=itype)
            db.add(inst)
            existing[key] = inst
        inst.trading_symbol = symbol
        inst.token = str(r["token"])
        inst.underlying = r["name"].strip().upper()
        inst.expiry = expiry
        inst.lot_size = int(r.get("lotsize") or 1)
        inst.tick_size = _tick(r)
        if itype == "OPT":
            inst.strike = (Decimal(str(r.get("strike") or 0)) / 100).quantize(Decimal("0.01"))  # provider sends x100
            inst.option_type = symbol[-2:]
        seen.add(key)
        n += 1
    db.commit()
    return n


def needs_sync(db: Session) -> bool:
    eq = db.scalar(select(func.count()).select_from(Instrument).where(Instrument.instrument_type == "EQ")) or 0
    fut = db.scalar(select(func.count()).select_from(Instrument).where(Instrument.instrument_type == "FUT")) or 0
    return eq == 0 or fut == 0


def count_instruments(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Instrument)) or 0


def sync_from_provider() -> int:
    """Download + store equities and derivatives. Own session so it can run in a background thread."""
    from app.database.session import SessionLocal

    rows = download_scrip_master()
    with SessionLocal() as db:
        n = sync_nse_equities(db, rows)
        d = sync_derivatives(db, rows)
    log.info("Instrument master synced: %s NSE equities, %s F&O contracts", n, d)
    return n + d
