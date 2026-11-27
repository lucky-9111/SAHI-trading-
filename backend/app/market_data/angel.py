"""Angel One SmartAPI provider. Credentials come from env only and never leave the backend."""
import logging
import threading
import time
from datetime import datetime

from app.core.config import get_settings
from app.market_data.provider import NoData, NotConfigured, ProviderError, RateLimited

log = logging.getLogger(__name__)

# Use the OS certificate store (fixes CERTIFICATE_VERIFY_FAILED behind antivirus/proxy TLS inspection).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    log.warning("truststore unavailable; using default CA bundle")


def _silence_sdk_logs():
    """The SmartAPI SDK logs request bodies (client code, MPIN, TOTP) on errors. Never let that reach our logs."""
    try:
        import logzero

        logzero.loglevel(logging.CRITICAL)
        logzero.logger.disabled = True
    except Exception:  # pragma: no cover
        pass


MIN_CALL_GAP = 0.4  # seconds; SmartAPI historical endpoint is ~3 req/s
SESSION_TTL = 6 * 3600


class AngelProvider:
    def __init__(self, client_factory=None):
        self._client = None
        self._logged_in_at = 0.0
        self._last_call = 0.0
        self._last_error: str | None = None
        self._last_ok: float | None = None
        self._lock = threading.Lock()
        self._factory = client_factory  # injectable for tests

    @staticmethod
    def configured() -> bool:
        s = get_settings()
        return all([s.angel_api_key, s.angel_client_code, s.angel_password, s.angel_totp_secret])

    def status(self) -> dict:
        if not self.configured():
            return {"state": "DISCONNECTED", "reason": "Angel One credentials are not set in backend/.env",
                    "last_updated": None}
        if self._last_error and not self._last_ok:
            return {"state": "DISCONNECTED", "reason": self._last_error, "last_updated": None}
        # Historical candles are not a live tick feed, so never claim LIVE here.
        state = "DELAYED" if self._last_ok else "DISCONNECTED"
        reason = "Historical candles only (no live tick feed yet)" if self._last_ok else "No successful request yet"
        return {"state": state, "reason": reason,
                "last_updated": datetime.fromtimestamp(self._last_ok).isoformat() if self._last_ok else None}

    def _login(self):
        s = get_settings()
        if not self.configured():
            raise NotConfigured("Angel One credentials are not set in backend/.env")
        for env_name, value in (("ANGEL_API_KEY", s.angel_api_key), ("ANGEL_CLIENT_CODE", s.angel_client_code),
                                ("ANGEL_PASSWORD", s.angel_password), ("ANGEL_TOTP_SECRET", s.angel_totp_secret)):
            if not (value.isascii() and value.isprintable() and " " not in value):
                self._last_error = (f"{env_name} in backend/.env has invalid characters (spaces or non-English "
                                    "symbols). Copy the real value again, not the hidden dots.")
                raise ProviderError(self._last_error)
        try:
            import pyotp
            if self._factory:
                client = self._factory()
            else:
                _silence_sdk_logs()
                from SmartApi import SmartConnect
                _silence_sdk_logs()
                client = SmartConnect(api_key=s.angel_api_key)
            res = client.generateSession(s.angel_client_code, s.angel_password,
                                         pyotp.TOTP(s.angel_totp_secret).now())
        except NotConfigured:
            raise
        except Exception as e:
            self._last_error = f"Login failed: {type(e).__name__}"
            raise ProviderError(self._last_error) from e
        if not res or not res.get("status"):
            msg = (res or {}).get("message", "unknown error")
            self._last_error = f"Angel One login rejected: {msg}"
            raise ProviderError(self._last_error)
        self._client, self._logged_in_at, self._last_error = client, time.time(), None
        log.info("Angel One session established")

    def _ensure(self):
        if self._client is None or time.time() - self._logged_in_at > SESSION_TTL:
            self._login()

    def get_candles(self, exchange: str, token: str, interval: str, start: datetime, end: datetime) -> list[list]:
        params = {"exchange": exchange, "symboltoken": token, "interval": interval,
                  "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
        res = self._request(lambda c: c.getCandleData(params))
        data = res.get("data") or []
        if not data:
            raise NoData("No candles returned for this range")
        return data

    def get_market_data(self, exchange_tokens: dict[str, list[str]]) -> list[dict]:
        """Batch quotes (up to 50 tokens): ltp, previous close, change, volume."""
        res = self._request(lambda c: c.getMarketData("FULL", exchange_tokens))
        return (res.get("data") or {}).get("fetched") or []

    def get_ltp(self, exchange: str, trading_symbol: str, token: str):
        from decimal import Decimal

        res = self._request(lambda c: c.ltpData(exchange, trading_symbol, token))
        ltp = (res.get("data") or {}).get("ltp")
        if ltp is None:
            raise NoData("No price returned")
        return Decimal(str(ltp))

    def _request(self, call) -> dict:
        with self._lock:
            for attempt in (1, 2):
                self._ensure()
                wait = MIN_CALL_GAP - (time.time() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.time()
                try:
                    res = call(self._client)
                except Exception as e:
                    msg = str(e).lower()
                    if "access denied" in msg or "rate" in msg:
                        raise RateLimited("Angel One rate limit hit, retry in a few seconds") from e
                    self._last_error = f"Request failed: {type(e).__name__}"
                    raise ProviderError(self._last_error) from e
                if res and res.get("status"):
                    self._last_ok = time.time()
                    return res
                code = str((res or {}).get("errorcode", ""))
                if attempt == 1 and code in ("AG8001", "AG8002", "AB1010"):  # invalid/expired token
                    self._client = None  # force fresh login, retry once
                    continue
                if "rate" in str((res or {}).get("message", "")).lower() or code == "AB1004":
                    raise RateLimited("Angel One rate limit hit, retry in a few seconds")
                raise ProviderError((res or {}).get("message") or "Angel One returned an error")
            raise ProviderError("Angel One session could not be re-established")


provider = AngelProvider()
