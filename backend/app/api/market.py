from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database.session import get_db
from app.market_data import angel
from app.market_data.provider import TIMEFRAMES, ProviderError, rows_to_candles, window_for
from app.models import User
from app.models.market import Instrument
from app.trading import pricing

router = APIRouter(prefix="/api/market", tags=["market"])

# (key, display name, exchange, provider token). Index tokens are fixed by the exchange/provider.
INDICES = [
    ("NIFTY50", "NIFTY 50", "NSE", "99926000"),
    ("BANKNIFTY", "BANK NIFTY", "NSE", "99926009"),
    ("SENSEX", "SENSEX", "BSE", "99919000"),
    ("FINNIFTY", "FIN NIFTY", "NSE", "99926037"),
    ("MIDCPNIFTY", "MIDCAP NIFTY", "NSE", "99926074"),
]
INDEX_BY_KEY = {k: (n, e, t) for k, n, e, t in INDICES}

LISTS = {
    "popular": ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "LT", "BHARTIARTL",
                "AXISBANK", "KOTAKBANK", "HINDUNILVR", "TATAMOTORS", "MARUTI", "SUNPHARMA", "WIPRO"],
    "etfs": ["NIFTYBEES", "BANKBEES", "JUNIORBEES", "GOLDBEES", "SILVERBEES", "LIQUIDBEES", "ITBEES", "PSUBNKBEES"],
}


def trend_label(pct: float) -> str:
    """Based only on today's % change vs previous close."""
    if pct >= 1.5:
        return "Strong uptrend"
    if pct >= 0.25:
        return "Uptrend"
    if pct <= -1.5:
        return "Strong downtrend"
    if pct <= -0.25:
        return "Downtrend"
    return "Sideways"


def quote_dict(q: pricing.Quote) -> dict:
    return {"ltp": str(q.ltp), "prev_close": str(q.prev_close), "change": str(q.change), "pct": str(q.pct),
            "volume": q.volume}


def stock_rows(db: Session, symbols: list[str]) -> list[dict]:
    insts = db.scalars(select(Instrument).where(Instrument.exchange == "NSE", Instrument.instrument_type == "EQ",
                                                Instrument.symbol.in_(symbols))).all()
    by_sym = {i.symbol: i for i in insts}
    ordered = [by_sym[s] for s in symbols if s in by_sym]
    try:
        quotes = pricing.get_quotes([(i.exchange, i.token) for i in ordered])
    except pricing.PriceUnavailable as e:
        raise HTTPException(503, f"Market data unavailable: {e}")
    rows = []
    for i in ordered:
        q = quotes.get((i.exchange, i.token))
        rows.append({"symbol": i.symbol, "exchange": i.exchange, "instrument_id": i.id,
                     **(quote_dict(q) if q else {"ltp": None, "prev_close": None, "change": None, "pct": None,
                                                  "volume": None})})
    return rows


@router.get("/status")
def status(_: User = Depends(current_user)):
    return angel.provider.status()


@router.get("/overview")
def overview(_: User = Depends(current_user)):
    """Index cards + trend labels. Every number comes from the provider; nothing is simulated."""
    try:
        quotes = pricing.get_quotes([(e, t) for _, _, e, t in INDICES])
    except pricing.PriceUnavailable as e:
        raise HTTPException(503, f"Market data unavailable: {e}")
    rows = []
    for key, name, ex, tok in INDICES:
        q = quotes.get((ex, tok))
        if q:
            rows.append({"key": key, "name": name, "exchange": ex, **quote_dict(q),
                         "trend": trend_label(float(q.pct))})
    return {"indices": rows, "market_open": pricing.is_market_open(),
            "as_of": datetime.now(pricing.IST).isoformat(), "status": angel.provider.status()}


@router.get("/quote/{symbol}")
def one_quote(symbol: str, exchange: str = "NSE", _: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = stock_rows_for(db, symbol.upper(), exchange.upper())
    return rows


def stock_rows_for(db: Session, symbol: str, exchange: str) -> dict:
    inst = db.scalar(select(Instrument).where(Instrument.exchange == exchange, Instrument.symbol == symbol,
                                              Instrument.instrument_type == "EQ"))
    if not inst:
        raise HTTPException(404, "Unknown instrument")
    try:
        q = pricing.get_quotes([(inst.exchange, inst.token)]).get((inst.exchange, inst.token))
    except pricing.PriceUnavailable as e:
        raise HTTPException(503, f"Market data unavailable: {e}")
    return {"symbol": inst.symbol, "exchange": inst.exchange, "instrument_id": inst.id,
            **(quote_dict(q) if q else {"ltp": None, "prev_close": None, "change": None, "pct": None, "volume": None})}


def _nearest_futures(db: Session, underlyings: list[str], exchange: str) -> list[tuple[str, Instrument]]:
    today = datetime.now(pricing.IST).date()
    out = []
    for u in underlyings:
        f = db.scalar(select(Instrument).where(Instrument.exchange == exchange, Instrument.instrument_type == "FUT",
                                               Instrument.underlying == u, Instrument.expiry >= today).order_by(Instrument.expiry))
        if f:
            out.append((u, f))
    return out


def _future_rows(db: Session, pairs: list[tuple[str, Instrument]], link_exchange: str | None = None) -> list[dict]:
    if not pairs:
        return []
    try:
        quotes = pricing.get_quotes([(f.exchange, f.token) for _, f in pairs])
    except pricing.PriceUnavailable as e:
        raise HTTPException(503, f"Market data unavailable: {e}")
    empty = {"ltp": None, "prev_close": None, "change": None, "pct": None, "volume": None}
    rows = []
    for u, f in pairs:
        q = quotes.get((f.exchange, f.token))
        rows.append({"symbol": u, "exchange": link_exchange or f.exchange, "instrument_id": f.id, "contract": f.symbol,
                     "expiry": f.expiry.isoformat() if f.expiry else None, "lot_size": f.lot_size,
                     **(quote_dict(q) if q else empty)})
    return rows


@router.get("/commodities")
def commodities(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Nearest-expiry MCX future of every listed commodity, with its live quote."""
    from app.market_data.instrument_master import MCX_UNDERLYINGS

    order = ["GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL"]
    names = order + sorted(MCX_UNDERLYINGS - set(order))
    return {"items": _future_rows(db, _nearest_futures(db, names, "MCX")),
            "market_open": pricing.is_market_open(exchange="MCX")}


FNO_INDEX = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]


@router.get("/fno")
def fno(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Nearest-expiry futures of the four indices and the popular F&O stocks, with live quotes."""
    stocks = [s for s in LISTS["popular"] if db.scalar(select(Instrument.id).where(
        Instrument.exchange == "NFO", Instrument.instrument_type == "FUT", Instrument.underlying == s).limit(1))]
    return {"indices": _future_rows(db, _nearest_futures(db, FNO_INDEX, "NFO"), "NSE"),
            "stocks": _future_rows(db, _nearest_futures(db, stocks, "NFO"), "NSE"),
            "market_open": pricing.is_market_open()}


@router.get("/ticks")
def ticks(s: str = Query(..., description="comma separated EXCHANGE:TOKEN, e.g. NSE:2885,MCX:575691"),
          _: User = Depends(current_user)):
    """Latest pushed price of each token, read from memory (no broker call). The browser prefers the /ws/ticks websocket; this is its fallback.
    Asking for a token keeps it subscribed for a couple of minutes."""
    from app.live import runtime

    specs = []
    for part in s.split(",")[:60]:
        ex, _, tok = part.partition(":")
        if ex and tok.isalnum():
            specs.append((ex.upper(), tok))
    runtime.touch(specs)
    out = {}
    for ex, tok in specs:
        t = runtime.store.get(ex, tok)
        if t is not None:
            out[f"{ex}:{tok}"] = {"ltp": t.ltp, "age": round(runtime.store.age(ex, tok) or 0.0, 1), "ts": int(t.exchange_ts.timestamp() * 1000),
                                  "state": runtime.store.state(ex, tok)}
    pl = runtime.pipeline
    return {"ticks": out, "feed": pl.feed_status() if pl else {"state": "closed", "last_tick_age_s": None},
            "as_of": datetime.now(pricing.IST).isoformat()}


@router.get("/lists/{name}")
def market_list(name: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    if name not in LISTS:
        raise HTTPException(404, "Unknown list")
    return {"name": name, "items": stock_rows(db, LISTS[name]), "market_open": pricing.is_market_open()}


@router.get("/candles")
def candles(symbol: str, timeframe: str = Query("15m"), exchange: str = "NSE",
            _: User = Depends(current_user), db: Session = Depends(get_db)):
    if timeframe not in TIMEFRAMES:
        raise HTTPException(422, f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    if symbol.upper() in INDEX_BY_KEY:
        _name, ex, token = INDEX_BY_KEY[symbol.upper()]
        label = symbol.upper()
    else:
        inst = db.scalar(select(Instrument).where(
            Instrument.exchange == exchange.upper(), Instrument.symbol == symbol.upper(),
            Instrument.instrument_type.in_(["EQ", "FUT"])))
        if not inst:
            raise HTTPException(404, "Unknown instrument")
        ex, token, label = inst.exchange, inst.token, inst.symbol
    now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    interval, start, end, rule = window_for(timeframe, now)
    try:
        rows = angel.provider.get_candles(ex, token, interval, start, end)
    except ProviderError as e:
        raise HTTPException(e.code, str(e))
    data = rows_to_candles(rows, rule)
    return {"symbol": label, "exchange": ex, "token": token, "timeframe": timeframe, "source": "Angel One SmartAPI",
            "candles": [c.__dict__ for c in data], "status": angel.provider.status()}
