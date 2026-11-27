"""Option-strategy payoff at expiry and theoretical Greeks (Black-Scholes). Adapted from the algo-main simulator.

A leg is a dict: side BUY|SELL, opt CE|PE, strike, qty (units = lots x lot size), entry (premium), optional iv (%) and
expiry (date). Greeks are THEORETICAL estimates; a leg without IV is left out of the Greeks (never an invented IV).
"""
from __future__ import annotations

import datetime as dt

from app.analytics import options_math as bs

RATE, DIV = 0.065, 0.0

PRESETS: dict[str, list[tuple[str, str, int]]] = {   # (side, opt, strikes from ATM; + = OTM)
    "Bull Call Spread": [("BUY", "CE", 0), ("SELL", "CE", 2)],
    "Bear Put Spread": [("BUY", "PE", 0), ("SELL", "PE", 2)],
    "Long Straddle": [("BUY", "CE", 0), ("BUY", "PE", 0)],
    "Long Strangle": [("BUY", "CE", 2), ("BUY", "PE", 2)],
    "Short Straddle": [("SELL", "CE", 0), ("SELL", "PE", 0)],
    "Short Strangle": [("SELL", "CE", 4), ("SELL", "PE", 4)],
    "Iron Condor": [("SELL", "CE", 4), ("SELL", "PE", 4), ("BUY", "CE", 8), ("BUY", "PE", 8)],
    "Iron Fly": [("SELL", "CE", 0), ("SELL", "PE", 0), ("BUY", "CE", 6), ("BUY", "PE", 6)],
    "Bull Put Credit Spread": [("SELL", "PE", 3), ("BUY", "PE", 6)],
    "Bear Call Credit Spread": [("SELL", "CE", 3), ("BUY", "CE", 6)],
}


def _sign(leg: dict) -> int:
    return 1 if leg["side"] == "BUY" else -1


def expiry_pnl(legs: list[dict], x: float) -> float:
    total = 0.0
    for l in legs:
        intrinsic = max(0.0, x - l["strike"]) if l["opt"] == "CE" else max(0.0, l["strike"] - x)
        total += (intrinsic - l["entry"]) * l["qty"] * _sign(l)
    return total


def payoff(legs: list[dict], spot: float, span_pct: float = 15.0, points: int = 121) -> dict:
    lo, hi = spot * (1 - span_pct / 100), spot * (1 + span_pct / 100)
    strikes = [l["strike"] for l in legs]
    lo, hi = min(lo, min(strikes) * 0.97), max(hi, max(strikes) * 1.03)
    xs = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    for k in strikes:                       # make sure every kink is on the curve
        if k not in xs:
            xs.append(float(k))
    xs.sort()
    ys = [expiry_pnl(legs, x) for x in xs]
    # slope beyond the last strike decides whether profit / loss is unbounded (price 0 bounds the left side)
    up = expiry_pnl(legs, hi * 2) - expiry_pnl(legs, hi)
    top, bottom = max(ys), min(ys)
    left_floor = expiry_pnl(legs, 0.0)
    max_profit = None if up > 1e-9 else max(top, left_floor)
    max_loss = None if up < -1e-9 else min(bottom, left_floor)
    bes = []
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if y0 == 0:
            bes.append(round(x0, 2))
        elif y0 * y1 < 0:
            bes.append(round(x0 + (x1 - x0) * (-y0) / (y1 - y0), 2))
    net = sum(l["entry"] * l["qty"] * (-_sign(l)) for l in legs)    # + credit received, - debit paid
    return {"curve": [[round(x, 2), round(y, 2)] for x, y in zip(xs, ys)], "max_profit": None if max_profit is None else round(max_profit, 2),
            "max_loss": None if max_loss is None else round(max_loss, 2), "breakevens": sorted(set(bes)), "net_credit": round(net, 2)}


def greeks(legs: list[dict], spot: float, on: dt.date, iv_shift: float = 0.0) -> dict:
    g = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    skipped = 0
    for l in legs:
        if not l.get("iv") or not l.get("expiry"):
            skipped += 1
            continue
        t = max((l["expiry"] - on).days + 0.25, 0.25) / 365.0
        lg = bs.greeks(spot, l["strike"], t, RATE, DIV, max((l["iv"] + iv_shift) / 100.0, 0.0001), l["opt"] == "CE")
        for k in g:
            g[k] += lg[k] * l["qty"] * _sign(l)
    return {"greeks": {k: round(v, 4 if k == "gamma" else 2) for k, v in g.items()}, "legs_without_iv": skipped}
