import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from types import SimpleNamespace

import pytest
from app import operations_check
from app.core.config import Settings, settings
from app.main import app
from app.services.health_service import ReadinessProbe
from app.services.worker_health import WorkerHealth
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url


@pytest.fixture(params=["sqlite", "postgres"])
def operations_client(request, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "operations.db")
    if request.param == "postgres":
        monkeypatch.setattr(settings, "database_url", SecretStr(request.getfixturevalue("pg_url")))
    with TestClient(app) as client:
        # Freeze worker diagnostics independently of the real background startup pass.
        health = WorkerHealth()
        health.begin()
        health.finish(created=0, today=date(2026, 10, 12), delay=60)
        app.state.worker_health = health
        yield client


def test_minimal_probes_are_public_and_details_require_owner(operations_client):
    for path in ("/api/health", "/api/health/ready", "/api/health/worker"):
        response = operations_client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["cache-control"] == "no-store"
    assert operations_client.get("/api/operations/health").status_code == 401
    assert operations_client.get("/api/health/worker/private").status_code == 401
    login_client(operations_client)
    response = operations_client.get("/api/operations/health")
    assert response.status_code == 200
    assert response.json()["database_ready"] is True
    assert response.json()["worker"]["last_created"] == 0
    assert response.headers["cache-control"] == "no-store"


def test_db_outage_does_not_break_liveness_or_in_memory_worker_probe(operations_client, monkeypatch):
    def broken():
        raise sqlite3.OperationalError("postgres://user:secret@host financial-description")

    monkeypatch.setattr(app.state.database, "check_ready", broken)
    response = operations_client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret" not in response.text
    assert operations_client.get("/api/health").json() == {"status": "ok"}
    assert operations_client.get("/api/health/worker").status_code == 200


def test_worker_failure_does_not_remove_healthy_db_from_service(operations_client):
    health = app.state.worker_health
    for _ in range(3):
        health.begin()
        health.finish(failure="invalid_data", delay=60)
    response = operations_client.get("/api/health/worker")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert operations_client.get("/api/health/ready").status_code == 200
    login_client(operations_client)
    details = operations_client.get("/api/operations/health").json()["worker"]
    assert details["consecutive_failures"] == 3
    assert details["last_error_code"] == "invalid_data"
    assert details["reasons"] == ["repeated_failures"]


def test_schema_damage_causes_readiness_failure_without_migration(operations_client):
    with app.state.database.connection() as connection:
        connection.execute("ALTER TABLE budgets RENAME COLUMN monthly_limit_cents TO unavailable_cents")
        connection.commit()
    assert operations_client.get("/api/health/ready").status_code == 503
    assert operations_client.get("/api/health").status_code == 200


def test_currency_mismatch_is_not_ready(operations_client):
    app.state.database.base_currency = "ZZZ"
    assert operations_client.get("/api/health/ready").status_code == 503


def test_process_pass_captures_one_business_date(db, monkeypatch):
    from datetime import UTC, datetime

    from app.domain import business_date
    from app.schemas import RecurringCreate
    from app.services.recurring_runner import process_pass

    instants = iter([datetime(2026, 10, 11, 21, 59, tzinfo=UTC), datetime(2026, 10, 11, 22, 1, tzinfo=UTC)])
    db.add_recurring(
        RecurringCreate(
            type="income",
            category="Daily",
            amount=1,
            frequency="daily",
            start_date=date(2026, 10, 10),
        )
    )
    monkeypatch.setattr(business_date, "utc_now", lambda: next(instants))
    assert process_pass(db.database) == (1, None, date(2026, 10, 11))
    assert business_date.today() == date(2026, 10, 12)


def test_readiness_is_single_flight_and_caches_success_and_failure():
    entered, release = Event(), Event()
    calls, now = [], [0.0]

    def probe():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return len(calls) == 1

    readiness = ReadinessProbe(SimpleNamespace(check_ready=probe), monotonic=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        first = pool.submit(readiness.ready)
        assert entered.wait(2)
        assert list(pool.map(lambda _: readiness.ready(), range(20))) == [False] * 20
        release.set()
        assert first.result(timeout=2) is True
    assert all(readiness.ready() for _ in range(20))
    assert len(calls) == 1
    now[0] = 5
    assert readiness.ready() is False
    assert not any(readiness.ready() for _ in range(20))
    assert len(calls) == 2
    now[0] = 10
    assert readiness.ready() is False
    assert len(calls) == 3


def test_readiness_recovers_after_failed_cache_expires():
    now, calls = [0.0], []

    def probe():
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("sensitive")
        return True

    readiness = ReadinessProbe(SimpleNamespace(check_ready=probe), monotonic=lambda: now[0])
    assert readiness.ready() is False
    assert readiness.ready() is False
    assert len(calls) == 1
    now[0] = 5
    assert readiness.ready() is True
    assert len(calls) == 2


def test_postgres_readiness_times_out_on_schema_lock(pg_url):
    import time

    import psycopg
    from app.postgres_database import PostgresDatabase
    from app.services.auth_service import initialize_auth

    database = PostgresDatabase(pg_url)
    try:
        initialize_auth(database)
        assert database.check_ready() is True
        with database.connection() as writer, writer.raw.transaction():
            writer.raw.execute("LOCK TABLE accounts IN ACCESS EXCLUSIVE MODE")
            started = time.monotonic()
            with pytest.raises((psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled)):
                database.check_ready()
            assert time.monotonic() - started < 5
        assert database.check_ready() is True
    finally:
        database.close()


def test_sqlite_probe_is_read_only_and_does_not_create_missing_database(db):
    from app.services.auth_service import initialize_auth

    initialize_auth(db.database)
    assert db.database.check_ready() is True
    original = db.database.db_path
    db.database.db_path = original + ".missing"
    with pytest.raises(sqlite3.OperationalError):
        db.database.check_ready()
    from pathlib import Path

    assert not Path(db.database.db_path).exists()
    db.database.db_path = original


def test_startup_grace_has_a_finite_limit(operations_client):
    now = [0.0]
    app.state.worker_health = WorkerHealth(monotonic=lambda: now[0], stale_seconds=10)
    assert operations_client.get("/api/health/worker").json() == {"status": "starting"}
    now[0] = 11
    assert operations_client.get("/api/health/worker").status_code == 503


@pytest.mark.parametrize(
    "kwargs",
    [
        {"recurring_interval_seconds": 0},
        {"recurring_failure_threshold": 0},
        {"recurring_lag_days": 0},
        {"recurring_stale_seconds": 0},
        {"recurring_interval_seconds": 400, "recurring_max_backoff_seconds": 300},
    ],
)
def test_monitoring_settings_are_validated(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    "value",
    [
        "http://public.example",
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com?secret=x",
        "https://example.com#fragment",
        "https://example.com:invalid",
        "https://[invalid",
    ],
)
def test_monitor_rejects_unsafe_origins(value):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        operations_check.origin(value)


def test_monitor_exit_status_and_sanitized_output(monkeypatch, capsys):
    class Connection:
        status = 200
        body = b'{"status":"ok"}'

        def __init__(self, host, port, timeout):
            assert host == "example.com"
            assert timeout == 5

        def request(self, method, path):
            assert method == "GET"
            assert path.startswith("/api/health")

        def getresponse(self):
            return self

        def close(self):
            pass

        def read(self, limit):
            assert limit == 256
            return self.body

    monkeypatch.setattr(operations_check.http.client, "HTTPSConnection", Connection)
    assert operations_check.main(["--url", "https://example.com"]) == 0
    assert set(json.loads(capsys.readouterr().out).values()) == {"ok"}

    Connection.status = 503
    Connection.body = b'{"status":"unavailable","secret":"hidden"}'
    assert operations_check.main(["--url", "https://example.com"]) == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    assert set(json.loads(output).values()) == {"unavailable"}
    for status, body in (
        (302, b'{"status":"ok"}'),
        (200, b"invalid"),
        (200, b"[]"),
        (200, b'{"status":[]}'),
    ):
        Connection.status, Connection.body = status, body
        assert operations_check.main(["--url", "https://example.com"]) == 1
        assert set(json.loads(capsys.readouterr().out).values()) == {"unavailable"}
