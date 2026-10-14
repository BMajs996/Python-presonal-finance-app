"""Failed connection configuration must not leak a database connection."""

import sqlite3
from unittest.mock import Mock

import pytest
from app.database import FinanceDatabase
from app.postgres_database import PostgresDatabase


def test_sqlite_configuration_failure_closes_connection(tmp_path, monkeypatch):
    class FailingConnection(sqlite3.Connection):
        def execute(self, query, *args):
            if query == "PRAGMA journal_mode = WAL":
                raise sqlite3.OperationalError("synthetic configuration failure")
            return super().execute(query, *args)

    path = tmp_path / "failed.db"
    connection = sqlite3.connect(path, factory=FailingConnection)
    monkeypatch.setattr(sqlite3, "connect", lambda *_args, **_kwargs: connection)
    with pytest.raises(sqlite3.OperationalError, match="synthetic configuration"):
        FinanceDatabase(path)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_postgres_configuration_failure_closes_connection(monkeypatch):
    from app import postgres_database

    raw = Mock()
    raw.execute.side_effect = RuntimeError("synthetic configuration failure")
    monkeypatch.setattr(postgres_database.psycopg, "connect", lambda *_args, **_kwargs: raw)
    database = PostgresDatabase.__new__(PostgresDatabase)
    database._url = "postgresql:///synthetic_test"
    with pytest.raises(RuntimeError, match="synthetic configuration"):
        database.connect()
    raw.close.assert_called_once_with()
