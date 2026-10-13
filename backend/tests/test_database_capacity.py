from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from app.database_errors import DatabaseCapacityError
from app.main import app
from app.postgres_database import PostgresDatabase
from psycopg import sql
from psycopg_pool import PoolTimeout, TooManyRequests

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pool_size": 0},
        {"pool_size": 21},
        {"pool_timeout": 0},
        {"pool_max_waiting": 0},
    ],
)
def test_pool_rejects_unbounded_settings_before_connecting(kwargs):
    with pytest.raises(ValueError, match="out of bounds"):
        PostgresDatabase("postgresql:///unused", **kwargs)


def test_pool_reuses_connections_and_clears_session_and_uncommitted_work(pg_url):
    database = PostgresDatabase(pg_url, pool_size=1)
    try:
        with database.connection() as connection:
            pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
            schema = connection.execute("SELECT current_schema()").fetchone()[0]
            connection.execute("CREATE TEMP TABLE pool_private (id integer)")
            connection.execute("SET lock_timeout='1ms'")
            connection.execute("SET search_path=pg_catalog")
            connection.execute("BEGIN IMMEDIATE")
            connection.raw.execute(
                sql.SQL("INSERT INTO {}.settings VALUES ('uncommitted','test')").format(
                    sql.Identifier(schema)
                )
            )
        with database.connection() as connection:
            assert connection.execute("SELECT pg_backend_pid()").fetchone()[0] == pid
            assert connection.execute("SELECT current_schema()").fetchone()[0] == schema
            assert connection.execute("SHOW lock_timeout").fetchone()[0] == "10s"
            assert connection.execute("SHOW statement_timeout").fetchone()[0] == "1min"
            assert connection.execute("SELECT to_regclass('pool_private')").fetchone()[0] is None
            assert (
                connection.execute("SELECT COUNT(*) FROM settings WHERE key='uncommitted'").fetchone()[0] == 0
            )
            assert connection.raw.prepare_threshold is None
    finally:
        database.close()


def wait_for_pool_stat(database, name, value):
    deadline = monotonic() + 2
    while database.pool.get_stats()[name] != value and monotonic() < deadline:
        Event().wait(0.01)
    assert database.pool.get_stats()[name] == value


def test_pool_timeout_is_bounded_and_capacity_recovers(pg_url):
    database = PostgresDatabase(pg_url, pool_size=1, pool_timeout=2, pool_max_waiting=1)
    try:
        with database.connection():
            database.pool.timeout = 0.2
            with pytest.raises(DatabaseCapacityError) as error:
                with database.connection():
                    pass
            assert isinstance(error.value.__cause__, PoolTimeout)
        # Reset callbacks run in the pool worker before a returned connection is reusable.
        wait_for_pool_stat(database, "pool_available", 1)
        with database.connection() as connection:
            assert connection.execute("SELECT 1").fetchone()[0] == 1
        assert database.pool.get_stats()["pool_size"] == 1
    finally:
        database.close()


def test_pool_queue_limit_rejects_excess_and_serves_existing_waiter(pg_url):
    database = PostgresDatabase(pg_url, pool_size=1, pool_timeout=5, pool_max_waiting=1)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            with database.connection():

                def request_connection():
                    with database.connection() as connection:
                        return connection.execute("SELECT 1").fetchone()[0]

                future = workers.submit(request_connection)
                wait_for_pool_stat(database, "requests_waiting", 1)
                with pytest.raises(DatabaseCapacityError) as error:
                    with database.connection():
                        pass
                assert isinstance(error.value.__cause__, TooManyRequests)
                assert not future.done()
            assert future.result(timeout=3) == 1
        assert database.pool.get_stats()["pool_size"] == 1
    finally:
        database.close()


def test_pool_returns_usable_connection_after_exception(pg_url):
    database = PostgresDatabase(pg_url, pool_size=1)
    try:
        with pytest.raises(RuntimeError, match="synthetic"):
            with database.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("INSERT INTO settings VALUES ('failed','test')")
                raise RuntimeError("synthetic")
        with database.connection() as connection:
            assert connection.execute("SELECT COUNT(*) FROM settings WHERE key='failed'").fetchone()[0] == 0
    finally:
        database.close()


def test_pool_replaces_a_disconnected_backend(pg_url):
    database = PostgresDatabase(pg_url, pool_size=1)
    try:
        with database.connection() as connection:
            pid = connection.execute("SELECT pg_backend_pid()").fetchone()[0]
        assert database.conn.execute("SELECT pg_terminate_backend(?)", (pid,)).fetchone()[0]
        with database.connection() as connection:
            assert connection.execute("SELECT pg_backend_pid()").fetchone()[0] != pid
            assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        database.close()


def test_capacity_error_is_sanitized_for_auth_and_financial_routes(raw_client, monkeypatch):
    from contextlib import contextmanager

    login_client(raw_client)

    @contextmanager
    def unavailable():
        raise DatabaseCapacityError("synthetic private connection details")
        yield

    monkeypatch.setattr(app.state.database, "connection", unavailable)
    for method, path, kwargs in (
        ("get", "/api/accounts", {}),
        ("post", "/api/auth/login", {"json": {"username": "owner", "password": "synthetic"}}),
    ):
        response = getattr(raw_client, method)(path, **kwargs)
        assert response.status_code == 503
        assert response.headers["retry-after"] == "2"
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"detail": "Database is busy. Try again shortly."}
