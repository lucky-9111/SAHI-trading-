import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
import threading

from app.api import accounts, auth, dashboard, derivatives, instruments, market, trading, watchlists
from app.live import runtime, ws as live_ws
from app.core.config import get_settings
from app.database.session import Base, engine, ensure_columns
import app.models  # noqa: F401  (register models)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev convenience; Alembic migrations are the source of truth for schema changes.
    Base.metadata.create_all(engine)
    ensure_columns()
    if not os.environ.get("DISABLE_AUTO_SYNC"):
        from app.database.session import SessionLocal
        from app.market_data.instrument_master import needs_sync

        with SessionLocal() as db:
            empty = needs_sync(db)
        if empty:
            instruments.start_sync_if_needed()
    stop = threading.Event()
    if not os.environ.get("DISABLE_ENGINE"):
        from app.trading import poller

        poller.start(stop)  # fallback price loop (REST); the live pipeline below does the same from pushed ticks
        if get_settings().feed_mode != "off":
            from app.live.pipeline import Pipeline

            pl = Pipeline(mode=get_settings().feed_mode)
            runtime.pipeline = pl
            await pl.start()
            live_ws.manager.start(pl)
            replay_file = os.environ.get("REPLAY_FILE")
            if pl.mode == "replay" and replay_file:
                from app.live import replay

                asyncio.ensure_future(replay.play(pl, replay_file, float(os.environ.get("REPLAY_SPEED", "1"))))
    yield
    stop.set()
    if runtime.pipeline is not None:
        live_ws.manager.stop()
        await runtime.pipeline.stop()
        runtime.pipeline = None


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, accounts.router, dashboard.router, instruments.router, market.router, trading.router,
          trading.strategies_router, watchlists.router,
          derivatives.router):
    app.include_router(r)


app.include_router(live_ws.router)


@app.get("/api/live/health")
@app.get("/health")
def live_health():
    """Is the live feed connected, how old is the last tick per exchange, queue sizes, last candle closed, error count."""
    pl = runtime.pipeline
    if pl is None:
        return {"mode": "off", "feed": {"state": "closed", "connected": False}, "error_count": 0}
    return pl.health()


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name, "paper_trading_only": True}
