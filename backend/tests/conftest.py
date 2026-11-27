import os

# Must be set before the app is imported
os.environ["DATABASE_URL"] = "sqlite:///./test_agroup.db"
os.environ["DISABLE_AUTO_SYNC"] = "1"
os.environ["DISABLE_ENGINE"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"

import pytest
from fastapi.testclient import TestClient

from app.database.session import Base, engine
from app.main import app


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
