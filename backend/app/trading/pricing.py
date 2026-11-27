"""Single source of prices for the paper engine. Never invents a price: raises PriceUnavailable instead."""
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.market_data import angel
from app.market_data.provider import ProviderError
from app.models.market import Instrument

IST = ZoneInfo("Asia/Kolkata")
CACHE_TTL = 3.0
_cache: dict[str, tuple[float, "PriceQuote"]] = {}


class PriceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class PriceQuote:
    price: Decimal
    as_of: datetime
    market_open: bool


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


@dataclass(frozen=True)
class Quote:
    exchange: str
    token: str
    ltp: Decimal
    prev_close: Decimal
    change: Decimal
    pct: Decimal
    volume: int


QUOTE_TTL = 10.0
_qcache: dict[tuple[str, str], tuple[float, Quote | None]] = {}  # None = provider returned nothing (negative cache)


def get_quotes(specs: list[tuple[str, str]], ttl: float = QUOTE_TTL) -> dict[tuple[str, str], Quote]:
    """specs: [(exchange, token)]. Batched + cached. Missing symbols are simply absent from the result.
    Raises PriceUnavailable only if nothing could be served (not even from a fresh cache)."""
    now = time.time()
    out: dict[tuple[str, str], Quote] = {}
    need: dict[str, list[str]] = {}
    for ex, tok in dict.fromkeys(specs):
        hit = _qcache.get((ex, tok))
        if hit and now - hit[0] <= ttl:
            if hit[1] is not None:
                out[(ex, tok)] = hit[1]
        else:
            need.setdefault(ex, []).append(tok)
    if need:
        try:
            for ex, toks in need.items():
                for i in range(0, len(toks), 50):
                    rows = angel.provider.get_market_data({ex: toks[i:i + 50]})
                    for r in rows:
                        q = Quote(r["exchange"], str(r["symbolToken"]), Decimal(str(r["ltp"])),
                                  Decimal(str(r.get("close") or 0)), Decimal(str(r.get("netChange") or 0)),
                                  Decimal(str(r.get("percentChange") or 0)), int(r.get("tradeVolume") or 0))
                        _qcache[(ex, q.token)] = (time.time(), q)
                        out[(ex, q.token)] = q
                    for tok in toks[i:i + 50]:
                        if (ex, tok) not in out:
                            _qcache[(ex, tok)] = (time.time(), None)
        except ProviderError as e:
            if not out:
                raise PriceUnavailable(str(e)) from e
    return out


def session_close(now: datetime | None = None) -> datetime:
    """When a DAY order placed at `now` expires: the close (15:30 IST) of the current session if the market has not
    closed yet on a weekday, otherwise of the next weekday. (Exchange holidays are not known to the app.)"""
    from datetime import timedelta

    now = (now or datetime.now(IST)).astimezone(IST)
    day = now.date()
    if now.weekday() >= 5 or now.time() > dtime(15, 30):
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    return datetime.combine(day, dtime(15, 30), tzinfo=IST)


def get_price(instrument: Instrument, max_age: float = CACHE_TTL) -> PriceQuote:
    key = f"{instrument.exchange}:{instrument.token}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] <= max_age:
        return hit[1]
    try:
        ltp = angel.provider.get_ltp(instrument.exchange, instrument.trading_symbol, instrument.token)
    except ProviderError as e:
        raise PriceUnavailable(str(e)) from e
    if ltp <= 0:
        raise PriceUnavailable("Provider returned an invalid price")
    quote = PriceQuote(ltp, datetime.now(IST), is_market_open())
    _cache[key] = (time.time(), quote)
    return quote
