import datetime as dt

from app.analytics import options_math as bs, payoff
from tests.conftest import register


def test_bs_put_call_parity_and_iv_roundtrip():
    c = bs.price(100, 100, 0.5, 0.065, 0, 0.2, True)
    p = bs.price(100, 100, 0.5, 0.065, 0, 0.2, False)
    assert abs((c - p) - (100 - 100 * 2.718281828 ** (-0.065 * 0.5))) < 1e-3
    assert abs(bs.implied_vol(c, 100, 100, 0.5, 0.065, 0, True) - 20.0) < 0.01


def test_bull_call_spread_payoff():
    legs = [dict(side="BUY", opt="CE", strike=100, qty=10, entry=6), dict(side="SELL", opt="CE", strike=110, qty=10, entry=2)]
    r = payoff.payoff(legs, 100)
    assert r["max_profit"] == 60.0 and r["max_loss"] == -40.0
    assert r["breakevens"] == [104.0] and r["net_credit"] == -40.0


def test_naked_short_call_is_unbounded():
    r = payoff.payoff([dict(side="SELL", opt="CE", strike=100, qty=1, entry=5)], 100)
    assert r["max_loss"] is None and r["max_profit"] == 5.0


def test_analyze_endpoint(client):
    h = register(client)
    exp = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    r = client.post("/api/derivatives/analyze", headers=h, json={"spot": 22000, "legs": [
        {"side": "SELL", "opt": "CE", "strike": 22000, "qty": 75, "entry": 150, "iv": 14, "expiry": exp},
        {"side": "SELL", "opt": "PE", "strike": 22000, "qty": 75, "entry": 140, "iv": 14, "expiry": exp}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["greeks"]["theta"] > 0 and j["max_loss"] is None and len(j["breakevens"]) == 2
    assert client.get("/api/derivatives/strategy-presets", headers=h).json()[0]["name"]
    assert client.post("/api/derivatives/analyze", headers=h, json={"spot": 1, "legs": []}).status_code == 422
