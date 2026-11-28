"""Single source of prices for the paper engine. Never invents a price: raises PriceUnavailable instead."""
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
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


SESSIONS = {"MCX": (dtime(9, 0), dtime(23, 30))}   # everything else trades 09:15-15:30
DEFAULT_SESSION = (dtime(9, 15), dtime(15, 30))


def session_hours(exchange: str = "NSE", day=None) -> tuple[dtime, dtime]:
    """(open, close) IST of that day (today by default); the DEFAULT hours when the exchange is closed all day."""
    from app.live import calendar

    return calendar.session(exchange, day or datetime.now(IST).date()) or DEFAULT_SESSION


def is_market_open(now: datetime | None = None, exchange: str = "NSE") -> bool:
    """Open per the market calendar: weekends, holidays, special sessions and late opens included (the backend clock decides)."""
    from app.trading import market_status

    return market_status.is_open(exchange, now)


@dataclass(frozen=True)
class Quote:
    exchange: str
    token: str
    ltp: Decimal
    prev_close: Decimal
    change: Decimal
    pct: Decimal
    volume: int
    oi: int = 0  # open interest (futures / options; 0 for equities)


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
                                  Decimal(str(r.get("percentChange") or 0)), int(r.get("tradeVolume") or 0),
                                  int(float(r.get("opnInterest") or 0)))
                        _qcache[(ex, q.token)] = (time.time(), q)
                        out[(ex, q.token)] = q
                    for tok in toks[i:i + 50]:
                        if (ex, tok) not in out:
                            _qcache[(ex, tok)] = (time.time(), None)
        except ProviderError as e:
            if not out:
                raise PriceUnavailable(str(e)) from e
    return out


def session_close(now: datetime | None = None, exchange: str = "NSE") -> datetime:
    """When a DAY order placed at `now` expires: the end of the current session if it has not ended yet, otherwise of the next trading
    day (weekends, holidays, special sessions and late opens come from the market calendar)."""
    from app.live import calendar
    from app.trading import market_status

    return calendar.next_close(exchange, now or market_status.now()).astimezone(IST)


def get_price(instrument: Instrument, max_age: float = CACHE_TTL) -> PriceQuote:
    key = f"{instrument.exchange}:{instrument.token}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] <= max_age:
        return hit[1]
    from app.live import runtime

    tick = runtime.fresh_tick(instrument.exchange, instrument.token, max_age=3.0)   # a pushed price a few seconds old beats a REST call
    if tick is not None:
        quote = PriceQuote(Decimal(str(tick.ltp)), datetime.now(IST), is_market_open(exchange=instrument.exchange))
        _cache[key] = (time.time(), quote)
        return quote
    if runtime.untrusted(instrument.exchange, instrument.token):
        raise PriceUnavailable("Price feed is stale (no ticks while the market is open); refusing to fill on an old price")
    try:
        ltp = angel.provider.get_ltp(instrument.exchange, instrument.trading_symbol, instrument.token)
    except ProviderError as e:
        raise PriceUnavailable(str(e)) from e
    if ltp <= 0:
        raise PriceUnavailable("Provider returned an invalid price")
    quote = PriceQuote(ltp, datetime.now(IST), is_market_open(exchange=instrument.exchange))
    _cache[key] = (time.time(), quote)
    return quote


# ---------------------------------------------------------------------------------------------------------------- execution prices
@dataclass(frozen=True)
class ExecQuote:
    """A price the paper engine may fill on: it traded in the CURRENT session of the instrument's exchange.

    bids / asks are the broker's best 5 levels (price, quantity), best first; empty when no fresh depth was available."""
    ltp: Decimal
    at: datetime                                   # UTC time of the trade behind `ltp`
    source: str                                    # "tick" (websocket) | "rest" (quote API) | "test"
    bids: tuple[tuple[Decimal, int], ...] = ()
    asks: tuple[tuple[Decimal, int], ...] = ()


FULL_TTL = 2.0
TRADE_TIME_FMT = "%d-%b-%Y %H:%M:%S"               # Angel quote API: exchTradeTime "27-Nov-2026 15:29:59" (IST)
_fcache: dict[str, tuple[float, dict | None]] = {}


def _full_quote(inst: Instrument) -> dict | None:
    """The broker's FULL quote row (ltp, last trade time, 5-level depth) of one instrument; None when unavailable. Cached 2 s."""
    key = f"{inst.exchange}:{inst.token}"
    hit = _fcache.get(key)
    if hit and time.time() - hit[0] <= FULL_TTL:
        return hit[1]
    row = None
    try:
        rows = angel.provider.get_market_data({inst.exchange: [str(inst.token)]})
        row = next((r for r in rows if str(r.get("symbolToken")) == str(inst.token)), None)
    except ProviderError:
        row = None
    _fcache[key] = (time.time(), row)
    return row


def trade_time(row: dict) -> datetime | None:
    raw = (row or {}).get("exchTradeTime") or ""
    try:
        return datetime.strptime(str(raw).strip(), TRADE_TIME_FMT).replace(tzinfo=IST).astimezone(timezone.utc)
    except ValueError:
        return None


def _levels(rows) -> tuple[tuple[Decimal, int], ...]:
    out = []
    for lv in rows or []:
        try:
            p, q = Decimal(str(lv.get("price") or 0)), int(float(lv.get("quantity") or 0))
        except (ArithmeticError, ValueError, TypeError):
            continue
        if p > 0 and q > 0:
            out.append((p, q))
    return tuple(out)


def depth(inst: Instrument, session_start: datetime) -> tuple[tuple, tuple]:
    """(bids, asks) from the broker's quote when it is from the current session, else ((), ()). Never raises.
    Off when PAPER_DEPTH_FILLS=false (then every fill takes the full quantity at the last traded price)."""
    from app.core.config import get_settings

    if not get_settings().paper_depth_fills:
        return (), ()
    row = _full_quote(inst)
    t = trade_time(row) if row else None
    if t is None or t < session_start:
        return (), ()
    d = row.get("depth") or {}
    return _levels(d.get("buy")), _levels(d.get("sell"))


def execution_quote(inst: Instrument, at: datetime | None = None) -> ExecQuote:
    """The first price that is safe to execute on, or PriceUnavailable. Rules:
      * the exchange must be in session (market status engine);
      * a websocket tick counts only if it traded in TODAY'S session (yesterday's last tick is not a price);
      * otherwise the broker quote API, and only if its last-trade time is inside today's session: right after the open the broker still
        reports the previous close as LTP, and that must never become an execution price;
      * nothing is used while the feed is down and the stored price is stale."""
    from app.live import calendar, runtime
    from app.trading import market_status

    n = (at or market_status.now()).astimezone(timezone.utc)
    b = calendar.session_bounds(inst.exchange, n.astimezone(IST).date())
    if not b or not (b[0] <= n <= b[1]):
        raise PriceUnavailable("The market is closed")
    start = b[0]
    if runtime.untrusted(inst.exchange, inst.token):
        raise PriceUnavailable("Price feed is stale (no ticks while the market is open); refusing to fill on an old price")
    tick = runtime.store.get(inst.exchange, inst.token)
    if tick is not None and tick.ltp > 0 and tick.utc >= start:
        return ExecQuote(Decimal(str(tick.ltp)), tick.utc, "tick")
    row = _full_quote(inst)
    if row is None:
        raise PriceUnavailable("No live quote from the broker")
    t = trade_time(row)
    ltp = Decimal(str(row.get("ltp") or 0))
    if t is None or t < start:
        raise PriceUnavailable("No trade yet in the current session (the broker still shows the previous close)")
    if ltp <= 0:
        raise PriceUnavailable("Provider returned an invalid price")
    d = row.get("depth") or {}
    return ExecQuote(ltp, t, "rest", _levels(d.get("buy")), _levels(d.get("sell")))
