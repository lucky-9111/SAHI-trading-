"""Production safety settings and health endpoints (no business logic)."""
from app.core.config import Settings

GOOD = dict(environment="production", secret_key="x" * 40, cors_origins="http://203.0.113.10",
            trusted_hosts="203.0.113.10", database_url="sqlite:////var/lib/sahi/sahi.db")


def test_development_has_no_production_checks():
    assert Settings(environment="development", secret_key="CHANGE_ME_IN_ENV").production_problems() == []


def test_valid_production_settings_pass():
    assert Settings(**GOOD).production_problems() == []


def test_production_rejects_unsafe_values_without_echoing_them():
    s = Settings(**{**GOOD, "secret_key": "CHANGE_ME_IN_ENV", "cors_origins": "*", "trusted_hosts": "*",
                    "database_url": "sqlite:///./agroup_trader.db"})
    problems = s.production_problems()
    assert len(problems) == 4
    assert not any("CHANGE_ME_IN_ENV" in p for p in problems)


def test_trusted_hosts_always_allow_local_health_checks():
    assert Settings(trusted_hosts="203.0.113.10").trusted_host_list == ["203.0.113.10", "localhost", "127.0.0.1"]
    assert Settings(trusted_hosts="*").trusted_host_list == ["*"]


def test_liveness_and_readiness(client):
    assert client.get("/api/health/live").json() == {"status": "ok"}
    r = client.get("/api/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readiness_reports_database_failure_without_details(client, monkeypatch):
    import app.main as main

    class Broken:
        def connect(self):
            raise RuntimeError("disk I/O error at /secret/path")

    monkeypatch.setattr(main, "engine", Broken())
    r = client.get("/api/health/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}
