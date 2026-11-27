from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.market import quote_dict
from app.database.session import get_db
from app.models import User, Watchlist, WatchlistStock
from app.models.market import Instrument
from app.trading import pricing

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class StockIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str = "NSE"


def _own(db: Session, user: User, wid: int) -> Watchlist:
    w = db.get(Watchlist, wid)
    if not w or w.user_id != user.id:
        raise HTTPException(404, "Watchlist not found")
    return w


def _render(db: Session, lists: list[Watchlist]) -> list[dict]:
    items = {}
    for w in lists:
        rows = db.execute(select(WatchlistStock, Instrument).join(Instrument, Instrument.id == WatchlistStock.instrument_id)
                          .where(WatchlistStock.watchlist_id == w.id).order_by(WatchlistStock.id)).all()
        items[w.id] = [i for _, i in rows]
    all_inst = {i.id: i for v in items.values() for i in v}
    quotes, prices_ok = {}, True
    if all_inst:
        try:
            quotes = pricing.get_quotes([(i.exchange, i.token) for i in all_inst.values()])
        except pricing.PriceUnavailable:
            prices_ok = False
    empty = {"ltp": None, "prev_close": None, "change": None, "pct": None, "volume": None}
    return [{"id": w.id, "name": w.name, "prices_available": prices_ok,
             "items": [{"instrument_id": i.id, "symbol": i.symbol, "exchange": i.exchange, "token": i.token,
                        **(quote_dict(quotes[(i.exchange, i.token)]) if (i.exchange, i.token) in quotes else empty)}
                       for i in items[w.id]]} for w in lists]


@router.get("")
def list_watchlists(user: User = Depends(current_user), db: Session = Depends(get_db)):
    lists = db.scalars(select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.id)).all()
    if not lists:  # first visit: give the user one empty list to start with
        db.add(Watchlist(user_id=user.id, name="My Watchlist"))
        db.commit()
        lists = db.scalars(select(Watchlist).where(Watchlist.user_id == user.id)).all()
    return _render(db, list(lists))


@router.post("", status_code=201)
def create(body: ListIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    w = Watchlist(user_id=user.id, name=body.name.strip())
    db.add(w)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A watchlist with this name already exists")
    return _render(db, [w])[0]


@router.delete("/{wid}", status_code=204)
def delete(wid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    w = _own(db, user, wid)
    for s in db.scalars(select(WatchlistStock).where(WatchlistStock.watchlist_id == wid)).all():
        db.delete(s)
    db.delete(w)
    db.commit()


@router.post("/{wid}/items", status_code=201)
def add_stock(wid: int, body: StockIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own(db, user, wid)
    inst = db.scalar(select(Instrument).where(Instrument.exchange == body.exchange.upper(),
                                              Instrument.symbol == body.symbol.upper(),
                                              Instrument.instrument_type == "EQ"))
    if not inst:
        raise HTTPException(404, "Unknown instrument")
    db.add(WatchlistStock(watchlist_id=wid, instrument_id=inst.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"{inst.symbol} is already in this watchlist")
    return {"symbol": inst.symbol}


@router.delete("/{wid}/items/{instrument_id}", status_code=204)
def remove_stock(wid: int, instrument_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own(db, user, wid)
    row = db.scalar(select(WatchlistStock).where(WatchlistStock.watchlist_id == wid,
                                                 WatchlistStock.instrument_id == instrument_id))
    if not row:
        raise HTTPException(404, "Stock not in watchlist")
    db.delete(row)
    db.commit()
