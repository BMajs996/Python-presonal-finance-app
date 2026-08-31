import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace

import pytest
from app.api.dependencies import get_finance_service
from app.database import FinanceDatabase
from app.repositories.finance_repository import FinanceRepository
from app.schemas import TransactionCreate


def transaction_payload(index: int) -> TransactionCreate:
    return TransactionCreate(
        date=date(2026, 8, 31),
        type="income",
        category="Concurrency",
        amount="1.00",
        description=f"Concurrent transaction {index}",
    )


def test_connections_apply_sqlite_safety_configuration(tmp_path):
    database = FinanceDatabase(tmp_path / "configured.db", busy_timeout_ms=1_234)
    try:
        with database.connection() as connection:
            assert connection is not database.conn
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1_234
            assert connection.isolation_level == "IMMEDIATE"

        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    finally:
        database.close()


def test_connection_context_rolls_back_unfinished_work(tmp_path):
    database = FinanceDatabase(tmp_path / "rollback.db")
    try:
        with pytest.raises(RuntimeError, match="request failed"):
            with database.connection() as connection:
                connection.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?)",
                    ("unfinished", "value"),
                )
                raise RuntimeError("request failed")

        assert (
            database.conn.execute("SELECT value FROM settings WHERE key = ?", ("unfinished",)).fetchone()
            is None
        )
    finally:
        database.close()


def test_concurrent_writes_use_independent_connections(tmp_path):
    database = FinanceDatabase(tmp_path / "concurrent.db")
    database.close()

    def add_transaction(index: int) -> int:
        with database.connection() as connection:
            repository = FinanceRepository(database, connection=connection)
            created = repository.add_transaction(transaction_payload(index))
            return created["id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        transaction_ids = list(executor.map(add_transaction, range(20)))

    assert len(set(transaction_ids)) == 20
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 20


def test_wal_allows_reads_during_an_active_write(tmp_path):
    database = FinanceDatabase(tmp_path / "read-during-write.db")
    try:
        with database.connection() as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("uncommitted", "value"),
            )

            with database.connection() as reader:
                assert reader.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
                assert (
                    reader.execute("SELECT value FROM settings WHERE key = ?", ("uncommitted",)).fetchone()
                    is None
                )
    finally:
        database.close()


def test_busy_timeout_rejects_a_second_writer_without_partial_data(tmp_path):
    database = FinanceDatabase(tmp_path / "locked.db", busy_timeout_ms=25)
    try:
        with database.connection() as first_writer:
            first_writer.execute("BEGIN IMMEDIATE")
            first_writer.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("first-writer", "pending"),
            )

            with database.connection() as second_writer:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    second_writer.execute(
                        "INSERT INTO settings(key, value) VALUES (?, ?)",
                        ("second-writer", "blocked"),
                    )

        assert (
            database.conn.execute(
                "SELECT COUNT(*) FROM settings WHERE key IN (?, ?)",
                ("first-writer", "second-writer"),
            ).fetchone()[0]
            == 0
        )
    finally:
        database.close()


def test_request_dependency_owns_and_closes_its_connection(tmp_path):
    database = FinanceDatabase(tmp_path / "request.db")
    database.close()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database=database)),
    )

    dependency = get_finance_service(request)
    service = next(dependency)
    connection = service.transactions_service.repository.conn
    assert service.accounts()[0]["name"] == "Main Account"

    dependency.close()

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
