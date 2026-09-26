import sqlite3
from datetime import date

import pytest
from app.database import FinanceDatabase
from app.migrations import LATEST_SCHEMA_VERSION, MONEY_COLUMNS, migrate
from app.repositories.finance_repository import FinanceRepository
from app.schemas import AccountCreate, BudgetCreate, RecurringCreate, TransactionCreate, TransferCreate

from .schema_helpers import remove_transaction_audit


@pytest.fixture
def populated(db):
    account = db.add_account(AccountCreate(name="Savings", opening_balance="-12.34"))
    db.add_transaction(
        TransactionCreate(date=date(2026, 1, 1), type="income", category="Salary", amount="0.30")
    )
    db.add_budget(BudgetCreate(category="Food", monthly_limit="25.50"))
    db.add_recurring(
        RecurringCreate(
            type="expense", category="Rent", amount="10.25", frequency="monthly", start_date=date(2026, 1, 1)
        )
    )
    db.add_transfer(
        TransferCreate(
            date=date(2026, 1, 1),
            from_account_id=db.accounts.default_account_id(),
            to_account_id=account["id"],
            amount="1.23",
        )
    )
    db.recurring_transactions.process_due(date(2026, 2, 1))
    return db


def remove_version_four(conn):
    with conn:
        remove_transaction_audit(conn)
        for table, _, _ in MONEY_COLUMNS:
            for operation in ("insert", "update"):
                conn.execute(f"DROP TRIGGER money_{table}_{operation}")
        conn.execute("DELETE FROM schema_migrations WHERE version=4")


@pytest.mark.parametrize("table,legacy,cents", MONEY_COLUMNS)
@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.parametrize("invalid", [None, 1.5, "not-money"])
def test_invalid_cent_storage_is_rejected(populated, table, legacy, cents, operation, invalid):
    conn = populated.database.conn
    row = dict(conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    row[cents] = invalid
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            if operation == "update":
                conn.execute(f"UPDATE {table} SET {cents}=? WHERE id=?", (invalid, row["id"]))
            else:
                row.pop("id")
                if table == "accounts":
                    row["name"] = "Another account"
                if table == "budgets":
                    row["category"] = "Another category"
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))


@pytest.mark.parametrize("table,legacy,cents", MONEY_COLUMNS)
@pytest.mark.parametrize("value", [None, "bad", 99.99])
def test_legacy_money_cannot_drift(populated, table, legacy, cents, value):
    conn = populated.database.conn
    with pytest.raises(sqlite3.IntegrityError, match="inconsistent money"):
        with conn:
            conn.execute(f"UPDATE {table} SET {legacy}=?", (value,))


@pytest.mark.parametrize("table,legacy,cents", [entry for entry in MONEY_COLUMNS if entry[0] != "accounts"])
@pytest.mark.parametrize("value", [0, -100])
def test_nonpositive_amounts_are_rejected_even_when_columns_agree(populated, table, legacy, cents, value):
    conn = populated.database.conn
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(f"UPDATE {table} SET {legacy}=?, {cents}=?", (value / 100, value))


def test_negative_and_zero_opening_balances_and_valid_money_updates(populated):
    conn = populated.database.conn
    for value in (-1234, 0, 1234):
        with conn:
            conn.execute(
                "UPDATE accounts SET opening_balance=?, opening_balance_cents=?", (value / 100, value)
            )
    for table, legacy, cents in MONEY_COLUMNS:
        with conn:
            conn.execute(f"UPDATE {table} SET {legacy}=?, {cents}=?", (12.34, 1234))
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_version_three_upgrade_preserves_rows_relationships_and_indexes(populated):
    conn = populated.database.conn
    remove_version_four(conn)
    tables = [table for table, _, _ in MONEY_COLUMNS] + ["recurring_occurrences"]
    before = {
        table: [
            {k: row[k] for k in row.keys() if k != "deleted_at"}
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
        ]
        for table in tables
    }
    indexes = list(
        conn.execute(
            """SELECT name, sql FROM sqlite_master WHERE type='index'
                AND tbl_name NOT IN ('reconciliations', 'reconciliation_entries')
                AND name NOT IN ('idx_transaction_audit_history', 'idx_transactions_deleted') ORDER BY name"""
        )
    )
    assert migrate(conn) == LATEST_SCHEMA_VERSION
    assert migrate(conn) == LATEST_SCHEMA_VERSION
    for table in tables:
        assert [
            {k: row[k] for k in row.keys() if k != "deleted_at"}
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
        ] == before[table]
    assert (
        list(
            conn.execute(
                """SELECT name, sql FROM sqlite_master WHERE type='index'
                AND tbl_name NOT IN ('reconciliations', 'reconciliation_entries')
                AND name NOT IN ('idx_transaction_audit_history', 'idx_transactions_deleted') ORDER BY name"""
            )
        )
        == indexes
    )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with populated.database.connection() as another:
        with pytest.raises(sqlite3.IntegrityError):
            another.execute("UPDATE transactions SET amount_cents=NULL")


@pytest.mark.parametrize("table,legacy,cents", MONEY_COLUMNS)
def test_bad_legacy_data_aborts_upgrade_atomically_and_can_be_repaired(populated, table, legacy, cents):
    conn = populated.database.conn
    remove_version_four(conn)
    with conn:
        conn.execute(f"UPDATE {table} SET {cents}=NULL")
    with pytest.raises(ValueError, match=f"Money validation failed in {table}, row"):
        migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 3
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'money_%'"
        ).fetchone()[0]
        == 0
    )
    assert conn.execute(f"SELECT {cents} FROM {table} LIMIT 1").fetchone()[0] is None
    with conn:
        conn.execute(f"UPDATE {table} SET {cents}=CAST(ROUND({legacy} * 100) AS INTEGER)")
    assert migrate(conn) == LATEST_SCHEMA_VERSION


@pytest.mark.parametrize("version", [1, 2, 3])
def test_historical_schema_upgrade_from_file(tmp_path, monkeypatch, version):
    import app.migrations as migrations

    path = tmp_path / f"version-{version}.db"
    with monkeypatch.context() as historical:
        historical.setattr(migrations, "LATEST_SCHEMA_VERSION", version)
        database = FinanceDatabase(path)
        with database.conn:
            database.conn.execute(
                "INSERT INTO transactions(date, type, category, amount, description, account_id) "
                "VALUES ('2026-01-01', 'income', 'Legacy', 12.34, '', 1)"
            )
            if version >= 2:
                database.conn.execute("UPDATE transactions SET amount_cents=1234")
        database.close()
    database = FinanceDatabase(path)
    try:
        repository = FinanceRepository(database)
        assert repository.list_transactions()[0][0]["amount"] == 12.34
        assert (
            database.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            == LATEST_SCHEMA_VERSION
        )
        assert database.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert database.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        database.close()
