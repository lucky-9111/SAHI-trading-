from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.market import INDEX_BY_KEY, quote_dict
from app.database.session import get_db
from app.models import User
from app.models.market import Instrument
from app.trading import pricing

router = APIRouter(prefix="/api/derivatives", tags=["derivatives"])

# F&O index underlyings -> the key of the matching index in api.market.INDICES (for spot price and chart)
INDEX_UNDERLYINGS = {"NIFTY": "NIFTY50", "BANKNIFTY": "BANKNIFTY", "FINNIFTY": "FINNIFTY", "MIDCPNIFTY": "MIDCPNIFTY"}
CHAIN_WINDOW = 12  # strikes shown on each side of ATM


def _spot(db: Session, underlying: str) -> dict:
    """Spot price + the chart symbol for an underlying. ltp is None when market data is unavailable."""
    mcx = _contracts(db, underlying, "FUT", "MCX")
    if mcx:   # commodity: its price is the nearest future; chart that contract
        try:
            q = pricing.get_quotes([(mcx[0].exchange, mcx[0].token)]).get((mcx[0].exchange, mcx[0].token))
        except pricing.PriceUnavailable:
            q = None
        return {"ltp": str(q.ltp) if q else None, "chart_symbol": mcx[0].symbol, "chart_exchange": "MCX"}
    if underlying in INDEX_UNDERLYINGS:
        key = INDEX_UNDERLYINGS[underlying]
        _name, ex, tok = INDEX_BY_KEY[key]
        chart = {"chart_symbol": key, "chart_exchange": ex}
    else:
        eq = db.scalar(select(Instrument).where(Instrument.exchange == "NSE", Instrument.symbol == underlying,
                                                Instrument.instrument_type == "EQ"))
        if not eq:
            return {"ltp": None, "chart_symbol": underlying, "chart_exchange": "NSE"}
        ex, tok = eq.exchange, eq.token
        chart = {"chart_symbol": eq.symbol, "chart_exchange": eq.exchange}
    try:
        q = pricing.get_quotes([(ex, tok)]).get((ex, tok))
    except pricing.PriceUnavailable:
        q = None
    return {"ltp": str(q.ltp) if q else None, **chart}


def _contracts(db: Session, underlying: str, itype: str, exchange: str | None = None) -> list[Instrument]:
    today = date.today()
    q = select(Instrument).where(Instrument.underlying == underlying, Instrument.instrument_type == itype, Instrument.expiry >= today)
    if exchange:
        q = q.where(Instrument.exchange == exchange)
    return list(db.scalars(q.order_by(Instrument.expiry, Instrument.strike, Instrument.option_type)))


@router.get("/{underlying}/expiries")
def expiries(underlying: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    u = underlying.upper()
    futs = _contracts(db, u, "FUT")
    opt_expiries = sorted({c.expiry for c in _contracts(db, u, "OPT")})
    if not futs and not opt_expiries:
        raise HTTPException(404, f"{u} has no futures or options")
    quotes = {}
    if futs:
        try:
            quotes = pricing.get_quotes([(f.exchange, f.token) for f in futs])
        except pricing.PriceUnavailable:
            pass
    sp = _spot(db, u)
    return {
        "underlying": u, "is_index": u in INDEX_UNDERLYINGS, "spot": sp["ltp"], "chart_symbol": sp["chart_symbol"],
        "chart_exchange": sp["chart_exchange"],
        "lot_size": (futs[0].lot_size if futs else _contracts(db, u, "OPT")[0].lot_size),
        "futures": [{"instrument_id": f.id, "symbol": f.symbol, "exchange": f.exchange, "token": f.token, "expiry": f.expiry.isoformat(), "lot_size": f.lot_size,
                     **({**quote_dict(quotes[(f.exchange, f.token)]), "oi": quotes[(f.exchange, f.token)].oi}
                        if (f.exchange, f.token) in quotes else {})}
                    for f in futs],
        "option_expiries": [e.isoformat() for e in opt_expiries],
    }


@router.get("/{underlying}/chain")
def chain(underlying: str, expiry: date = Query(...), _: User = Depends(current_user),
          db: Session = Depends(get_db)):
    u = underlying.upper()
    contracts = [c for c in _contracts(db, u, "OPT") if c.expiry == expiry]
    if not contracts:
        raise HTTPException(404, "No option contracts for this expiry")
    spot = _spot(db, u)
    strikes = sorted({c.strike for c in contracts})
    atm = None
    window = strikes
    if spot["ltp"] is not None:
        s = Decimal(spot["ltp"])
        atm = min(strikes, key=lambda k: abs(k - s))
        i = strikes.index(atm)
        window = strikes[max(0, i - CHAIN_WINDOW): i + CHAIN_WINDOW + 1]
    else:
        window = strikes[:2 * CHAIN_WINDOW + 1]
    shown = [c for c in contracts if c.strike in window]
    quotes = {}
    try:
        quotes = pricing.get_quotes([(c.exchange, c.token) for c in shown])
    except pricing.PriceUnavailable:
        pass

    def leg(c: Instrument | None):
        if c is None:
            return None
        q = quotes.get((c.exchange, c.token))
        return {"instrument_id": c.id, "symbol": c.symbol, "lot_size": c.lot_size, "token": c.token, "exchange": c.exchange,
                "ltp": str(q.ltp) if q else None, "pct": str(q.pct) if q else None}

    by = {(c.strike, c.option_type): c for c in shown}
    return {"underlying": u, "expiry": expiry.isoformat(), "spot": spot["ltp"], "atm_strike": str(atm) if atm else None,
            "lot_size": contracts[0].lot_size,
            "rows": [{"strike": str(k), "ce": leg(by.get((k, "CE"))), "pe": leg(by.get((k, "PE")))} for k in window]}


# ---- strategy payoff / Greeks analyzer (ported from the algo-main options simulator) -------------------------------------------------------
from datetime import date as _date  # noqa: E402
from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from app.analytics import payoff as _payoff  # noqa: E402


class LegIn(BaseModel):
    side: Literal["BUY", "SELL"]
    opt: Literal["CE", "PE"]
    strike: float = Field(gt=0)
    qty: int = Field(gt=0, description="units = lots x lot size")
    entry: float = Field(ge=0, description="premium per unit")
    iv: float | None = Field(default=None, gt=0, description="implied volatility in %")
    expiry: _date | None = None


class AnalyzeIn(BaseModel):
    spot: float = Field(gt=0)
    legs: list[LegIn] = Field(min_length=1, max_length=8)
    on: _date | None = None
    iv_shift: float = 0.0
    span_pct: float = Field(default=15.0, gt=0, le=60)


@router.get("/strategy-presets")
def strategy_presets(_: User = Depends(current_user)):
    return [{"name": n, "legs": [{"side": s, "opt": o, "offset": k} for s, o, k in legs]} for n, legs in _payoff.PRESETS.items()]


@router.post("/analyze")
def analyze(body: AnalyzeIn, _: User = Depends(current_user)):
    legs = [l.model_dump() for l in body.legs]
    out = _payoff.payoff(legs, body.spot, body.span_pct)
    out.update(_payoff.greeks(legs, body.spot, body.on or _date.today(), body.iv_shift))
    return out
