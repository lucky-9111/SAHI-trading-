"""Estimated NSE transaction charges and approximate margins. ALL ESTIMATES: rates change, and real F&O margin
(SPAN + exposure) needs exchange data this app does not have. Both are labelled as estimates in the UI."""
from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")

# Approximate margin assumptions for paper trading
FUT_MARGIN_PCT = Decimal("0.15")  # of contract value, long or short
OPT_SELL_MARGIN_PCT = Decimal("0.15")  # of (strike x quantity) when writing options

CASH_PRODUCTS = {"INTRADAY", "DELIVERY", "SWING"}
DERIV_PRODUCTS = {"INTRADAY", "NRML"}


def q2(x: Decimal) -> Decimal:
    return Decimal(x).quantize(TWO, rounding=ROUND_HALF_UP)


def estimate_charges(product: str, leg: str, turnover: Decimal, itype: str = "EQ") -> Decimal:
    """Charges for ONE leg. leg is the order side of that leg: 'BUY' or 'SELL'. turnover = price x quantity."""
    t = Decimal(turnover)
    sell = leg == "SELL"
    if itype == "FUT":
        brokerage = min(Decimal(20), t * Decimal("0.0003"))
        stt = t * Decimal("0.000125") if sell else Decimal(0)
        exchange = t * Decimal("0.0000183")
        stamp = t * Decimal("0.00002") if not sell else Decimal(0)
    elif itype == "OPT":
        brokerage = Decimal(20) if t > 0 else Decimal(0)
        stt = t * Decimal("0.001") if sell else Decimal(0)  # on premium
        exchange = t * Decimal("0.0003503")
        stamp = t * Decimal("0.00003") if not sell else Decimal(0)
    else:
        carry = product in ("DELIVERY", "SWING")
        brokerage = Decimal(0) if carry else min(Decimal(20), t * Decimal("0.0003"))
        stt = t * Decimal("0.001") if carry else (t * Decimal("0.00025") if sell else Decimal(0))
        exchange = t * Decimal("0.0000297")
        stamp = Decimal(0) if sell else t * (Decimal("0.00015") if carry else Decimal("0.00003"))
    sebi = t * Decimal("0.000001")
    gst = (brokerage + exchange + sebi) * Decimal("0.18")
    return q2(brokerage + stt + exchange + sebi + stamp + gst)


def required_cash(itype: str, side: str, price: Decimal, qty: int, strike: Decimal | None = None) -> Decimal:
    """Cash locked when opening. Equity/long options: full value. Futures / short options: approximate margin."""
    notional = q2(price * qty)
    if itype == "FUT":
        return q2(notional * FUT_MARGIN_PCT)
    if itype == "OPT":
        if side == "BUY":
            return notional
        return q2((strike or Decimal(0)) * qty * OPT_SELL_MARGIN_PCT)
    return notional
