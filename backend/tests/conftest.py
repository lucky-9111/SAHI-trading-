import os

# Must be set before the app is imported
os.environ["DATABASE_URL"] = "sqlite:///./test_agroup.db"
os.environ["DISABLE_AUTO_SYNC"] = "1"
os.environ["DISABLE_ENGINE"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["PAPER_DEPTH_FILLS"] = "0"          # tests that need market depth patch pricing.depth themselves

import pytest
from fastapi.testclient import TestClient

from app.database.session import Base, engine
from app.main import app


# The engine's clock in every test: Friday 27 Nov 2026, 09:30 IST (NSE open). Tests about closed markets move it.
TRADING_TIME = __import__("datetime").datetime(2026, 11, 27, 9, 30, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))


@pytest.fixture(autouse=True)
def market_clock():
    from app.live import calendar, runtime
    from app.trading import market_status, pricing

    market_status.set_clock(TRADING_TIME)
    pricing._fcache.clear()
    pricing._cache.clear()
    runtime.store._ticks.clear()          # a tick left by an earlier test must not make the worker skip an instrument
    runtime.store._at.clear()
    yield market_status.set_clock
    market_status.set_clock(None)
    calendar.invalidate()


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def register(client, email="a@example.com", name="Trader"):
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def auth(client):
    return register(client)


INTEGRATION_FIXTURES = {"client", "auth", "world"}


def pytest_collection_modifyitems(items):
    """Every test is either `unit` or `integration` (uses the TestClient / database), so CI can run them separately."""
    for item in items:
        fixtures = set(getattr(item, "fixturenames", ()))
        item.add_marker(pytest.mark.integration if fixtures & INTEGRATION_FIXTURES else pytest.mark.unit)
