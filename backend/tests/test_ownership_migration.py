import sqlite3

import psycopg
import pytest
from app import migrations, postgres_database
from app.database import FinanceDatabase
from app.domain import business_date
from app.postgres_connection import PostgresConnection, record_factory
from app.postgres_database import PostgresDatabase

from .postgres_helpers import pg_url as pg_url


@pytest.fixture(params=["sqlite", "postgres"])
def legacy(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        path = tmp_path / "legacy.db"
        with monkeypatch.context() as old:
            old.setattr(migrations, "LATEST_SCHEMA_VERSION", 7)
            database = FinanceDatabase(path)
        connection = database.conn

        def upgrade():
            return FinanceDatabase(path)

        version_table = "schema_migrations"
    else:
        url = request.getfixturevalue("pg_url")
        raw = psycopg.connect(url, autocommit=True, row_factory=record_factory)
        with raw.transaction(), monkeypatch.context() as old:
            old.setattr(postgres_database, "SCHEMA_VERSION", 2)
            postgres_database.create_schema(raw)
            postgres_database.install_guards(raw)
            raw.execute("INSERT INTO accounts(name,created_at) VALUES ('Main Account','test')")
        connection = PostgresConnection(raw)
        database = connection

        def upgrade():
            return PostgresDatabase(url)

        version_table = "postgres_schema_migrations"
    with connection:
        connection.execute(
            "INSERT INTO transactions(date,type,category,amount,amount_cents,account_id) "
            "VALUES (?,'income','Salary',12.34,1234,1)",
            (business_date.today().isoformat(),),
        )
        connection.execute(
            "INSERT INTO budgets(category,monthly_limit,monthly_limit_cents,month_year) "
            "VALUES ('Food',100,10000,?)",
            (business_date.today().strftime("%Y-%m"),),
        )
    try:
        yield connection, upgrade, version_table
    finally:
        database.close()


def snapshot(connection):
    return {
        table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
        for table in ("accounts", "budgets", "transactions", "transaction_audit")
    }


def test_upgrade_preserves_financial_rows_and_history_without_fabricating_contacts(legacy):
    connection, upgrade, _table = legacy
    before = snapshot(connection)
    database = upgrade()
    try:
        after = snapshot(database.conn)
        for table in ("accounts", "budgets"):
            for row in after[table]:
                assert row.pop("user_id") == 1
        assert after == before
        user = database.conn.execute("SELECT * FROM users WHERE id=1").fetchone()
        assert user["email"] is None and user["phone"] is None
        assert user["email_verified_at"] is None and user["phone_verified_at"] is None
        assert user["email_notifications"] == user["sms_notifications"] == user["monthly_reports"] == 0
    finally:
        database.close()
    retried = upgrade()
    retried.close()


def test_orphan_requires_owner_review_and_leaves_old_schema_unchanged(legacy):
    connection, upgrade, table = legacy
    with connection:
        connection.execute("UPDATE transactions SET account_id=NULL")
    before = snapshot(connection)
    version = connection.execute(f"SELECT MAX(version) FROM {table}").fetchone()[0]
    with pytest.raises(ValueError, match="owner review"):
        upgrade()
    assert snapshot(connection) == before
    assert connection.execute(f"SELECT MAX(version) FROM {table}").fetchone()[0] == version
    if isinstance(connection, sqlite3.Connection):
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
    else:
        assert connection.execute("SELECT to_regclass('users')").fetchone()[0] is None


def test_mid_upgrade_failure_rolls_back_and_retry_succeeds(legacy, monkeypatch):
    connection, upgrade, table = legacy
    before = snapshot(connection)
    version = connection.execute(f"SELECT MAX(version) FROM {table}").fetchone()[0]
    original = (
        migrations.migrate_ownership
        if isinstance(connection, sqlite3.Connection)
        else postgres_database.migrate_ownership
    )
    module = migrations if isinstance(connection, sqlite3.Connection) else postgres_database

    def fail(*args):
        original(*args)
        raise RuntimeError("synthetic ownership upgrade failure")

    with monkeypatch.context() as patch:
        patch.setattr(module, "migrate_ownership", fail)
        with pytest.raises(RuntimeError, match="synthetic ownership"):
            upgrade()
    assert snapshot(connection) == before
    assert connection.execute(f"SELECT MAX(version) FROM {table}").fetchone()[0] == version
    database = upgrade()
    database.close()


def test_identity_high_water_marks_survive_upgrade(legacy):
    connection, upgrade, _table = legacy
    if isinstance(connection, sqlite3.Connection):
        with connection:
            connection.execute(
                "INSERT INTO accounts(id,name,created_at,opening_balance_cents) "
                "VALUES (99,'Deleted legacy account','test',0)"
            )
            connection.execute("DELETE FROM accounts WHERE id=99")
    database = upgrade()
    try:
        with database.conn:
            user = database.conn.execute("INSERT INTO users DEFAULT VALUES RETURNING id").fetchone()[0]
            assert user == 2
            account = database.conn.execute(
                "INSERT INTO accounts(name,created_at,opening_balance_cents,user_id) "
                "VALUES ('Main Account','test',0,?) RETURNING id",
                (user,),
            ).fetchone()[0]
        if isinstance(connection, sqlite3.Connection):
            assert account > 99
    finally:
        database.close()


def test_sqlite_rebuild_validates_all_foreign_keys_and_restores_enforcement(legacy):
    connection, upgrade, table = legacy
    if not isinstance(connection, sqlite3.Connection):
        # PostgreSQL native FKs reject the same invalid transfer before migration.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection:
                connection.execute(
                    "INSERT INTO transfers(date,from_account_id,to_account_id,amount,"
                    "amount_cents,created_at) VALUES (?,1,999,1,100,'test')",
                    (business_date.today().isoformat(),),
                )
        return
    connection.execute("PRAGMA foreign_keys=OFF")
    with connection:
        connection.execute(
            "INSERT INTO transfers(date,from_account_id,to_account_id,amount,"
            "amount_cents,created_at) VALUES (?,1,999,1,100,'test')",
            (business_date.today().isoformat(),),
        )
    connection.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(ValueError, match="broken financial references"):
        upgrade()
    assert connection.execute(f"SELECT MAX(version) FROM {table}").fetchone()[0] == 7
    assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
