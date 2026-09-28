"""Read-only inventory of legacy future entries; never initializes or migrates a database."""

import sqlite3
from contextlib import closing
from pathlib import Path

import psycopg

from ..domain import business_date
from ..postgres_connection import PostgresConnection, record_factory


def inventory(connection, limit: int, offset: int):
    cutoff = business_date.today().isoformat()
    query = """
        SELECT 'transaction' AS kind, id, date, account_id, NULL AS to_account_id
        FROM transactions WHERE deleted_at IS NULL AND date>?
        UNION ALL
        SELECT 'transfer' AS kind, id, date, from_account_id AS account_id, to_account_id
        FROM transfers WHERE date>?
    """
    count = connection.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM transactions WHERE deleted_at IS NULL AND date>?)
          + (SELECT COUNT(*) FROM transfers WHERE date>?)
        """,
        (cutoff, cutoff),
    ).fetchone()[0]
    rows = connection.execute(
        query + " ORDER BY date,kind,id LIMIT ? OFFSET ?", (cutoff, cutoff, limit, offset)
    ).fetchall()
    return {"business_date": cutoff, "total": count, "items": [dict(row) for row in rows]}


def review_future_entries(path: Path, url: str | None = None, limit: int = 100, offset: int = 0):
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("Review requires limit 1-1000 and a non-negative offset")
    with business_date.snapshot():
        if url:
            with psycopg.connect(url, row_factory=record_factory, connect_timeout=10) as raw:
                raw.execute("SET TRANSACTION READ ONLY")
                return inventory(PostgresConnection(raw), limit, offset)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            return inventory(connection, limit, offset)
