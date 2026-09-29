"""Open an existing database without initialization, migrations or writes."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

import psycopg

from ..postgres_connection import PostgresConnection, record_factory


@contextmanager
def read_only_database(path: Path, url: str | None = None):
    if url:
        with psycopg.connect(url, row_factory=record_factory, connect_timeout=10) as raw:
            raw.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield PostgresConnection(raw)
    else:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            yield conn
