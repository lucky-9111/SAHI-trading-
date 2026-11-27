from datetime import datetime

from app.database.session import SessionLocal
from app.market_data import angel
from app.market_data.angel import AngelProvider
from app.market_data.instrument_master import sync_nse_equities
from app.market_data.provider import NotConfigured, rows_to_candles, window_for
from tests.test_instruments import ROWS

import pytest

DAILY = [
    ["2026-11-02T00:00:00+05:30", 100, 110, 95, 105, 1000],
    ["2026-11-03T00:00:00+05:30", 105, 120, 100, 118, 2000],
    ["2026-11-04T00:00:00+05:30", 118, 119, 90, 92, 3000],
    ["2026-11-09T00:00:00+05:30", 92, 99, 91, 98, 500],
]


def test_rows_to_candles_sorted_deduped_ist_shift():
    rows = [DAILY[1], DAILY[0], DAILY[0]]
    c = rows_to_candles(rows)
    assert [x.close for x in c] == [105.0, 118.0]
    assert c[0].time == 1793577600  # 2026-11-02 00:00 treated as UTC (IST wall clock)


def test_weekly_resample_ohlcv():
    c = rows_to_candles(DAILY, "W-FRI")
    wk1 = c[0]
    assert (wk1.open, wk1.high, wk1.low, wk1.close, wk1.volume) == (100, 120, 90, 92, 6000)
    assert len(c) == 2


def test_window_respects_provider_limits():
    for tf in ("1m", "5m", "15m", "30m", "1h", "1d", "1w", "1M"):
        _, s, e, _ = window_for(tf, datetime(2026, 11, 26))
        assert (e - s).days > 0


def test_provider_not_configured(monkeypatch):
    monkeypatch.setattr(AngelProvider, "configured", staticmethod(lambda: False))
    p = AngelProvider()
    assert p.status()["state"] == "DISCONNECTED"
    with pytest.raises(NotConfigured):
        p.get_candles("NSE", "2885", "ONE_DAY", datetime(2026, 1, 1), datetime(2026, 2, 1))


class FakeClient:
    def __init__(self):
        self.logins, self.fail_once = 0, True

    def generateSession(self, *a):
        self.logins += 1
        return {"status": True}

    def getCandleData(self, params):
        if self.fail_once:
            self.fail_once = False
            return {"status": False, "errorcode": "AG8002", "message": "Invalid Token"}
        return {"status": True, "data": DAILY}


def test_provider_relogs_in_on_expired_token(monkeypatch):
    monkeypatch.setattr(AngelProvider, "configured", staticmethod(lambda: True))
    fake = FakeClient()
    p = AngelProvider(client_factory=lambda: fake)
    monkeypatch.setattr("app.market_data.angel.MIN_CALL_GAP", 0)
    import pyotp
    monkeypatch.setattr(pyotp, "TOTP", lambda s: type("T", (), {"now": lambda self: "123456"})())
    rows = p.get_candles("NSE", "2885", "ONE_DAY", datetime(2026, 1, 1), datetime(2026, 2, 1))
    assert len(rows) == 4 and fake.logins == 2
    assert p.status()["state"] == "DELAYED"  # never LIVE for historical data


def test_candles_endpoint_503_when_unconfigured(client, auth, monkeypatch):
    monkeypatch.setattr(AngelProvider, "configured", staticmethod(lambda: False))
    with SessionLocal() as db:
        sync_nse_equities(db, ROWS)
    r = client.get("/api/market/candles", params={"symbol": "TCS", "timeframe": "1d"}, headers=auth)
    assert r.status_code == 503
    assert client.get("/api/market/candles", params={"symbol": "NOPE"}, headers=auth).status_code == 404
    assert client.get("/api/market/candles", params={"symbol": "TCS", "timeframe": "9x"}, headers=auth).status_code == 422
    assert client.get("/api/market/status", headers=auth).json()["state"] == "DISCONNECTED"
    assert angel.provider is not None
