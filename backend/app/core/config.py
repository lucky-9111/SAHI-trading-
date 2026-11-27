from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SAHI Trading"
    database_url: str = "sqlite:///./agroup_trader.db"
    secret_key: str = "CHANGE_ME_IN_ENV"
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    default_capital: str = "1000000"
    # paper-fill realism: adverse slippage in % applied to MARKET fills, trigger (stop) entries and stop-loss exits
    paper_slippage_pct: str = "0"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
