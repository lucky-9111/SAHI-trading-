from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

_url = get_settings().database_url
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(_url, connect_args={"check_same_thread": False} if _is_sqlite else {})

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


_NEW_COLUMNS = {
    "instruments": [("underlying", "VARCHAR(50)"), ("expiry", "DATE"), ("strike", "NUMERIC(12,2)"),
                    ("option_type", "VARCHAR(2)")],
    "positions": [("entry_value", "NUMERIC(18,2) DEFAULT 0")],
    "orders": [("validity", "VARCHAR(3) DEFAULT 'DAY'"), ("expires_at", "DATETIME"), ("trigger_price", "NUMERIC(14,2)"),
               ("filled_quantity", "INTEGER DEFAULT 0"), ("after_market", "BOOLEAN DEFAULT 0"), ("reduce_only", "BOOLEAN DEFAULT 0"),
               ("triggered_at", "DATETIME"), ("updated_at", "DATETIME")],
    "trades": [("order_id", "INTEGER")],
    "notifications": [("account_id", "INTEGER"), ("order_id", "INTEGER"), ("kind", "VARCHAR(30) DEFAULT ''"),
                      ("level", "VARCHAR(10) DEFAULT 'info'")],
    "users": [("role", "VARCHAR(10) DEFAULT 'user'"), ("is_owner", "BOOLEAN DEFAULT 0"), ("is_active", "BOOLEAN DEFAULT 1")],
    "risk_settings": [("after_hours_mode", "VARCHAR(6) DEFAULT 'REJECT'"), ("slippage_pct", "NUMERIC(6,3)")],
}


def ensure_columns() -> None:
    """Dev-time helper: add columns introduced after a table was first created (SQLite create_all never alters).
    Alembic remains the intended mechanism for production schema changes."""
    if not _is_sqlite:
        return
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _NEW_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        if insp.has_table("positions"):
            conn.execute(text("UPDATE positions SET entry_value = invested_amount "
                              "WHERE entry_value IS NULL OR entry_value = 0"))
    from app.database import migrations

    migrations.run(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
