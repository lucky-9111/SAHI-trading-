"""Runtime switches a developer flips from the console (stored in application_settings, read with a short cache).

  orders_enabled   off = new orders are refused for everyone (exits of open positions still go through)
  engine_enabled   off = the paper engine stops acting on prices: no fills, no stop-loss / target exits (EOD square-off still runs)
  signup_enabled   off = nobody can create an account on the sign-in page; admins add people in the console
"""
from __future__ import annotations

import time

from app.database.session import SessionLocal
from app.models import ApplicationSetting

SWITCHES = {
    "orders_enabled": ("New orders", "Off: every new order is refused with a clear message. Exits of open positions still work.", True),
    "engine_enabled": ("Paper engine", "Off: no fills, no stop-loss or target exits, no queued orders executed. Pages and data keep working.", True),
    "signup_enabled": ("Self sign-up", "Off: the sign-in page cannot create accounts; admins add people in the Users page.", True),
}
_TTL = 3.0
_cache: dict[str, tuple[float, bool]] = {}


def _key(name: str) -> str:
    return f"switch.{name}"


def get(name: str) -> bool:
    hit = _cache.get(name)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    default = SWITCHES[name][2]
    try:
        with SessionLocal() as db:
            row = db.get(ApplicationSetting, _key(name))
            val = default if row is None else row.value == "1"
    except Exception:  # noqa: BLE001  (a busy database must not stop trading decisions: use the default)
        val = default
    _cache[name] = (time.time(), val)
    return val


def set_(name: str, on: bool) -> None:
    if name not in SWITCHES:
        raise KeyError(name)
    with SessionLocal() as db:
        row = db.get(ApplicationSetting, _key(name))
        if row is None:
            db.add(ApplicationSetting(key=_key(name), value="1" if on else "0"))
        else:
            row.value = "1" if on else "0"
        db.commit()
    _cache.pop(name, None)


def all_() -> list[dict]:
    return [{"name": k, "label": v[0], "help": v[1], "on": get(k), "default": v[2]} for k, v in SWITCHES.items()]


def clear_cache() -> None:
    _cache.clear()
