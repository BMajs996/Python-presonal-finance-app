from datetime import date
from unittest.mock import Mock

import pytest
from app.postgres_database import PostgresDatabase

from benchmarks.run import request, snapshot
from benchmarks.server import seed, validate_database_url

from .postgres_helpers import pg_url as pg_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql:///finance_dashboard",
        "postgresql://example.com/finance_test",
        "sqlite:///finance_test",
        "postgresql:///finance_test?host=example.com",
        "postgresql:///finance_test?service=production",
        "postgresql:///finance_test?dbname=production",
    ],
)
def test_benchmark_refuses_nonlocal_or_nontest_database(url):
    with pytest.raises(ValueError):
        validate_database_url(url)


def test_benchmark_server_requires_generated_search_path():
    assert validate_database_url("postgresql:///finance_test")
    with pytest.raises(ValueError):
        validate_database_url("postgresql:///finance_test", isolated=True)
    with pytest.raises(ValueError):
        validate_database_url("postgresql:///finance_test?options=-csearch_path=public", isolated=True)


@pytest.mark.parametrize(
    "base",
    [
        "https://centspan.online",
        "http://localhost:8000",
        "http://127.0.0.1:8000/path",
        "http://user@127.0.0.1:8000",
    ],
)
def test_benchmark_http_rejects_other_origins_before_connecting(base):
    with pytest.raises(ValueError):
        request(base, "/api/health")


@pytest.mark.parametrize("rows", [0, 100001])
def test_benchmark_seed_is_bounded_before_sql(rows):
    database = Mock()
    with pytest.raises(ValueError):
        seed(database, rows, date(2026, 10, 13))
    database.conn.execute.assert_not_called()


def test_benchmark_seed_and_fingerprint_use_only_disposable_schema(pg_url):
    database = PostgresDatabase(pg_url)
    try:
        seed(database, 1000, date(2026, 10, 13))
        before = snapshot(pg_url)
        assert before["transactions"][0] == 1000
        assert before["transaction_audit"][0] == 1000
        assert before["accounts"][0] == 100
        assert before["transfers"][0] == 1000
        assert (
            database.conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE account_id=1 AND type='expense'"
            ).fetchone()[0]
            > 0
        )
        with pytest.raises(ValueError, match="fresh isolated"):
            seed(database, 1000, date(2026, 10, 13))
        assert snapshot(pg_url) == before
        with database.conn:
            database.conn.execute("UPDATE transactions SET description='Changed' WHERE id=1")
        assert snapshot(pg_url) != before
    finally:
        database.close()
