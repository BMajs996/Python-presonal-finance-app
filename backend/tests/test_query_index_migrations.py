import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from app.database import FinanceDatabase
from app.domain import business_date
from app.migrations import LATEST_SCHEMA_VERSION, migrate
from app.migrations_query_indexes import INDEXES
from app.postgres_database import SCHEMA_VERSION, PostgresDatabase
from app.schemas import TransactionCreate

from .postgres_helpers import pg_url as pg_url


def remove_indexes(connection):
    for name in INDEXES:
        connection.execute("DROP INDEX " + name)


def test_sqlite_index_upgrade_is_atomic_and_retryable(db):
    transaction = db.add_transaction(
        TransactionCreate(date=business_date.today(), type="income", category="Salary", amount="12.34")
    )
    with db.conn:
        remove_indexes(db.conn)
        db.conn.execute("DELETE FROM schema_migrations WHERE version=7")

    created = 0

    def authorize(action, _arg1, _arg2, _database, _trigger):
        nonlocal created
        if action == sqlite3.SQLITE_CREATE_INDEX:
            created += 1
            if created == 2:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.conn.set_authorizer(authorize)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            migrate(db.conn)
    finally:
        db.conn.set_authorizer(None)
    assert db.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 6
    names = {row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert not set(INDEXES) & names
    assert migrate(db.conn) == LATEST_SCHEMA_VERSION
    assert migrate(db.conn) == LATEST_SCHEMA_VERSION
    assert db.get_transaction(transaction["id"]) == transaction


def test_concurrent_sqlite_index_upgrade_rechecks_version_under_writer_lock(db, monkeypatch):
    from app import migrations

    path = db.database.db_path
    with db.conn:
        remove_indexes(db.conn)
        db.conn.execute("DELETE FROM schema_migrations WHERE version=7")
    db.close()
    barrier = Barrier(2)
    version = migrations._schema_version

    def read_version(connection):
        current = version(connection)
        if current == 6 and not connection.in_transaction:
            barrier.wait(timeout=5)
        return current

    monkeypatch.setattr(migrations, "_schema_version", read_version)

    def upgrade():
        database = FinanceDatabase(path)
        try:
            return database.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(upgrade) for _ in range(2)]
        assert [future.result(timeout=10) for future in futures] == [LATEST_SCHEMA_VERSION] * 2


def test_postgres_version_one_upgrade_rolls_back_and_can_retry(pg_url, monkeypatch):
    from app import postgres_database

    database = PostgresDatabase(pg_url)
    with database.conn.raw.transaction():
        remove_indexes(database.conn)
        database.conn.execute("DELETE FROM postgres_schema_migrations WHERE version=2")
        database.conn.execute("INSERT INTO settings VALUES ('preserved','value')")
    database.close()

    def fail_after_first(connection):
        name, definition = next(iter(INDEXES.items()))
        connection.execute(f"CREATE INDEX {name} {definition}")
        raise RuntimeError("synthetic migration failure")

    with monkeypatch.context() as patch:
        patch.setattr(postgres_database, "migrate_query_indexes", fail_after_first)
        with pytest.raises(RuntimeError, match="synthetic migration"):
            PostgresDatabase(pg_url)
    with psycopg.connect(pg_url) as raw:
        assert raw.execute("SELECT MAX(version) FROM postgres_schema_migrations").fetchone()[0] == 1
        names = {
            row[0]
            for row in raw.execute("SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()")
        }
        assert not set(INDEXES) & names
    database = PostgresDatabase(pg_url)
    try:
        assert (
            database.conn.execute("SELECT MAX(version) FROM postgres_schema_migrations").fetchone()[0]
            == SCHEMA_VERSION
        )
        assert (
            database.conn.execute("SELECT value FROM settings WHERE key='preserved'").fetchone()[0] == "value"
        )
        from app.services.auth_service import initialize_auth

        initialize_auth(database)
        assert database.check_ready()
    finally:
        database.close()


@pytest.mark.parametrize("versions", [(1, 3), (2,), (1, 2, 999), (1, 2147483647), (0, 1), ()])
def test_postgres_rejects_unknown_or_gapped_migration_history(pg_url, versions):
    database = PostgresDatabase(pg_url)
    database.close()
    with psycopg.connect(pg_url) as raw:
        raw.execute("DELETE FROM postgres_schema_migrations")
        for version in versions:
            raw.execute("INSERT INTO postgres_schema_migrations VALUES (%s)", (version,))
    with pytest.raises(ValueError, match="Unsupported PostgreSQL schema"):
        PostgresDatabase(pg_url)


def test_unknown_postgres_version_is_rejected_before_expanding_history(monkeypatch):
    from unittest.mock import Mock

    from app import postgres_database

    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [(1,), (2147483647,)]

    def forbidden_range(*_args):
        raise AssertionError("Unsupported version must not allocate its range")

    monkeypatch.setattr(postgres_database, "range", forbidden_range, raising=False)
    with pytest.raises(ValueError, match="Unsupported PostgreSQL schema"):
        postgres_database.migrate_schema(connection)
    assert connection.execute.call_count == 1


@pytest.mark.parametrize("versions", [(1, 3), (2,), (1, 2147483647), (0, 1)])
def test_sqlite_rejects_unknown_or_gapped_history_without_changing_rows(db, versions):
    transaction = db.add_transaction(
        TransactionCreate(date=business_date.today(), type="income", category="Salary", amount="12.34")
    )
    with db.conn:
        db.conn.execute("DELETE FROM schema_migrations")
        db.conn.executemany(
            "INSERT INTO schema_migrations VALUES (?,?)", [(version, "test") for version in versions]
        )
    with pytest.raises(ValueError, match="Unsupported SQLite schema"):
        migrate(db.conn)
    assert db.get_transaction(transaction["id"]) == transaction
    assert [
        row[0] for row in db.conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    ] == list(versions)
