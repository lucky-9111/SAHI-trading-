import threading
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.derivatives import INDEX_UNDERLYINGS
from app.database.session import get_db
from app.market_data import instrument_master as im
from app.models import User
from app.models.market import Instrument

router = APIRouter(prefix="/api/instruments", tags=["instruments"])
log = logging.getLogger(__name__)
_sync_state = {"running": False, "error": None}


def _run_sync():
    _sync_state.update(running=True, error=None)
    try:
        im.sync_from_provider()
    except Exception as e:  # network/parse failure must be visible, not silent
        log.exception("Instrument sync failed")
        _sync_state["error"] = str(e)
    finally:
        _sync_state["running"] = False


def start_sync_if_needed(force: bool = False) -> bool:
    if _sync_state["running"]:
        return False
    threading.Thread(target=_run_sync, daemon=True).start()
    return True


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=50), limit: int = Query(10, ge=1, le=50),
           _: User = Depends(current_user), db: Session = Depends(get_db)):
    term = q.strip().upper()
    # exact symbol first, then prefix, then substring
    rank = case((Instrument.symbol == term, 0), (Instrument.symbol.like(f"{term}%"), 1), else_=2)
    rows = db.scalars(
        select(Instrument)
        .where(Instrument.instrument_type == "EQ",
               Instrument.symbol.like(f"%{term}%") | Instrument.name.ilike(f"%{q.strip()}%"))
        .order_by(rank, Instrument.symbol).limit(limit)
    ).all()
    out = [{"id": i.id, "symbol": i.symbol, "name": i.name, "exchange": i.exchange,
            "instrument_type": i.instrument_type} for i in rows if i.instrument_type == "EQ"]
    # Index underlyings are tradable only through futures/options
    idx = [{"id": -n, "symbol": u, "name": None, "exchange": "NSE", "instrument_type": "IDX"}
           for n, u in enumerate(INDEX_UNDERLYINGS, 1) if len(term) >= 3 and u.startswith(term)]
    return (idx + out)[:limit]


@router.get("/status")
def status(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"count": im.count_instruments(db), "syncing": _sync_state["running"], "error": _sync_state["error"]}


@router.post("/sync", status_code=202)
def sync(_: User = Depends(current_user)):
    if not start_sync_if_needed(force=True):
        raise HTTPException(409, "Sync already running")
    return {"started": True}
