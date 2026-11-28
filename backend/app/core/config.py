import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SAHI Trading"
    # development | test | production. Production refuses to start with unsafe settings (see validate_production).
    environment: str = "development"
    # Host headers the backend accepts (comma separated). localhost/127.0.0.1 are always allowed for health checks.
    trusted_hosts: str = "*"
    database_url: str = "sqlite:///./agroup_trader.db"
    secret_key: str = "CHANGE_ME_IN_ENV"
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    default_capital: str = "1000000"
    # paper-fill realism: adverse slippage in % applied to MARKET fills, trigger (stop) entries and stop-loss exits
    paper_slippage_pct: str = "0"
    # fill against the broker's 5-level bid/ask depth when a fresh quote has it (BUY at the asks, SELL at the bids, partial fills when the
    # visible size is smaller than the order). Off = every fill takes the full quantity at the last traded price
    paper_depth_fills: bool = True
    # intraday positions are squared off this many minutes before the exchange's session end (0 = at the end)
    intraday_squareoff_minutes_before_close: int = 0
    # "live" = Angel websocket, "replay" = ticks from a recorded file (see scripts/replay.py), "off" = no pipeline
    feed_mode: str = "live"

    # Angel One SmartAPI (read from env only; never sent to the frontend)
    angel_api_key: str = ""
    angel_client_code: str = ""
    angel_password: str = ""
    angel_totp_secret: str = ""

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def trusted_host_list(self) -> list[str]:
        hosts = [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]
        if "*" in hosts:
            return ["*"]
        return hosts + [h for h in ("localhost", "127.0.0.1") if h not in hosts]

    def production_problems(self) -> list[str]:
        """Settings that must never reach production. Messages name the variable, never its value."""
        if not self.is_production:
            return []
        problems = []
        if self.secret_key in ("CHANGE_ME_IN_ENV", "generate-a-long-random-string") or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be a random string of at least 32 characters")
        if not self.cors_list or "*" in self.cors_list:
            problems.append("CORS_ORIGINS must list explicit origins (no '*')")
        if self.trusted_host_list == ["*"]:
            problems.append("TRUSTED_HOSTS must list the public host name / IP (no '*')")
        db_path = self.database_url.split(":///", 1)[-1]
        if self.database_url.startswith("sqlite") and not (db_path.startswith("/") or os.path.isabs(db_path)):
            problems.append("DATABASE_URL must be an absolute sqlite path (sqlite:////var/lib/sahi/sahi.db)")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
