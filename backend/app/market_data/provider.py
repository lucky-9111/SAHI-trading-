"""Market-data provider interface + candle utilities. Nothing here ever fabricates prices."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd

IST_OFFSET_SECONDS = 19800  # chart times are shifted so the browser axis shows IST


class ProviderError(Exception):
    """Base for provider failures. `code` maps to an HTTP status in the API layer."""
    code = 502


class NotConfigured(ProviderError):
    code = 503


class RateLimited(ProviderError):
    code = 429


class NoData(ProviderError):
    code = 404


@dataclass(frozen=True)
class Candle:
    time: int  # epoch seconds, IST-shifted
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketDataProvider(Protocol):
    def status(self) -> dict: ...
    def get_candles(self, exchange: str, token: str, interval: str, start: datetime, end: datetime) -> list[list]: ...


# timeframe -> (Angel interval, max days per request, lookback days we ask for, resample rule)
TIMEFRAMES: dict[str, tuple[str, int, int, str | None]] = {
    "1m": ("ONE_MINUTE", 30, 5, None),
    "5m": ("FIVE_MINUTE", 100, 20, None),
    "15m": ("FIFTEEN_MINUTE", 200, 60, None),
    "30m": ("THIRTY_MINUTE", 200, 90, None),
    "1h": ("ONE_HOUR", 400, 180, None),
    "1d": ("ONE_DAY", 2000, 730, None),
    "1w": ("ONE_DAY", 2000, 1825, "W-FRI"),
    "1M": ("ONE_DAY", 2000, 1950, "ME"),
}


def window_for(timeframe: str, now: datetime) -> tuple[str, datetime, datetime, str | None]:
    interval, max_days, lookback, rule = TIMEFRAMES[timeframe]
    return interval, now - timedelta(days=min(lookback, max_days)), now, rule


def rows_to_candles(rows: list[list], rule: str | None = None) -> list[Candle]:
    """rows: [[iso_timestamp, o, h, l, c, v], ...] as returned by the provider."""
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"])
    df["t"] = pd.to_datetime(df["t"].astype(str).str.slice(0, 19))  # drop tz suffix: already IST wall time
    df = df.drop_duplicates("t").sort_values("t").set_index("t")
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    if rule:
        df = df.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    out = []
    for ts, r in df.iterrows():
        epoch = int(pd.Timestamp(ts).tz_localize("UTC").timestamp())  # wall-clock IST treated as UTC
        out.append(Candle(epoch, r.open, r.high, r.low, r.close, int(r.volume)))
    return out
