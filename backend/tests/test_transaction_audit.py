import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from app.database import FinanceDatabase
from app.domain.errors import InvalidOperation, NotFound
from app.migrations import migrate
from app.repositories.finance_repository import FinanceRepository
from app.schemas import AccountCreate, BudgetCreate, TransactionCreate
from app.services.backup_service import BackupService


def payload(**changes):
    return TransactionCreate(
        **{
            "date": date.today(),
            "type": "expense",
            "category": "Food",
            "amount": "12.34",
            "description": "Lunch",
            **changes,
        }
    )


def test_lifecycle_records_exact_snapshots_and_idempotent_recovery(db):
    original = db.add_transaction(payload())
    ident = original["id"]
    assert db.update_transaction(ident, payload(amount="20.50"))["amount"] == 20.50
    assert db.delete_transaction(ident)
    assert not db.delete_transaction(ident)
    assert db.get_transaction(ident) is None
    assert db.update_transaction(ident, payload()) is None
    assert db.list_transactions() == ([], 0)
    deleted, count = db.transactions.list(deleted=True)
    assert count == 1 and deleted[0]["deleted_at"]
    restored = db.transactions.restore(ident)
    assert restored["id"] == ident and restored["amount"] == 20.50
    assert db.transactions.restore(ident) == restored
    events = db.transactions.history(ident)["items"]
    assert [event["action"] for event in events] == ["restored", "deleted", "updated", "created"]
    assert events[-1]["before_state"] is None
    assert events[-1]["after_state"]["amount_cents"] == 1234
    assert events[2]["before_state"]["amount_cents"] == 1234
    assert events[2]["after_state"]["amount_cents"] == 2050
    assert all(event["actor"] == "local" and event["occurred_at"].endswith("Z") for event in events)
    assert db.transactions.history(ident, limit=1, offset=2) == {"items": [events[2]], "total": 4}
    assert db.transactions.history(ident, offset=100)["items"] == []
    db.update_transaction(ident, payload(amount="20.50"))
    assert db.transactions.history(ident)["total"] == 4


def test_deleted_entries_are_excluded_from_every_financial_projection(db, finance_service):
    db.add_budget(BudgetCreate(category="Food", monthly_limit="100"))
    baseline = (finance_service.dashboard(), finance_service.monthly_report(), db.categories())
    entries = [
        db.add_transaction(payload(date=date.today() - timedelta(days=days), type=kind))
        for days in (0, 40, 400)
        for kind in ("expense", "income")
    ]
    populated = (finance_service.dashboard(), finance_service.monthly_report(), db.categories())
    assert populated != baseline
    for entry in entries:
        db.delete_transaction(entry["id"])
    assert (finance_service.dashboard(), finance_service.monthly_report(), db.categories()) == baseline
    for entry in entries:
        db.transactions.restore(entry["id"])
    assert (finance_service.dashboard(), finance_service.monthly_report(), db.categories()) == populated


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM transactions",
        "DELETE FROM transaction_audit",
        "UPDATE transaction_audit SET actor='changed'",
    ],
)
def test_history_and_retained_transactions_cannot_be_removed(db, sql):
    entry = db.add_transaction(payload())
    with pytest.raises(sqlite3.IntegrityError):
        with db.conn:
            db.conn.execute(sql)
    assert db.get_transaction(entry["id"]) == entry
    assert db.transactions.history(entry["id"])["total"] == 1


@pytest.mark.parametrize("operation", ["create", "update", "delete", "restore"])
def test_failed_audit_insert_rolls_back_financial_write(db, operation):
    entry = db.add_transaction(payload())
    ident = entry["id"]
    if operation == "restore":
        db.delete_transaction(ident)
    before = db.transactions.history(ident)
    current = db.get_transaction(ident)
    db.conn.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON transaction_audit
        BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="audit unavailable"):
        if operation == "create":
            db.add_transaction(payload())
        elif operation == "update":
            db.update_transaction(ident, payload(amount="99.99"))
        elif operation == "delete":
            db.delete_transaction(ident)
        else:
            db.transactions.restore(ident)
    assert db.get_transaction(ident) == current
    assert db.transactions.history(ident) == before
    assert db.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_concurrent_restore_records_one_event(db):
    ident = db.add_transaction(payload())["id"]
    db.delete_transaction(ident)
    barrier = Barrier(3)

    def restore():
        with db.database.connection() as conn:
            repo = FinanceRepository(db.database, connection=conn)
            barrier.wait(timeout=5)
            return repo.transactions.restore(ident)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(restore) for _ in range(3)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1] == results[2]
    assert db.transactions.history(ident)["total"] == 3
    assert db.get_account(results[0]["account_id"])["balance"] == -12.34


def test_restore_rejects_inactive_account_and_missing_transaction(db):
    account = db.add_account(AccountCreate(name="Cash"))
    ident = db.add_transaction(payload(account_id=account["id"]))["id"]
    db.delete_transaction(ident)
    db.deactivate_account(account["id"])
    with pytest.raises(InvalidOperation):
        db.transactions.restore(ident)
    assert db.get_transaction(ident) is None
    assert db.transactions.history(ident)["total"] == 2
    with pytest.raises(NotFound):
        db.transactions.restore(99999)
    with pytest.raises(NotFound):
        db.transactions.history(99999)


def test_backup_retains_deleted_entries_and_history(db, tmp_path):
    ident = db.add_transaction(payload())["id"]
    db.delete_transaction(ident)
    history = db.transactions.history(ident)
    archive = BackupService(db.database.db_path).create_backup(tmp_path / "audit.financebackup")
    destination = tmp_path / "restored.db"
    BackupService(destination).restore_backup(archive)
    database = FinanceDatabase(destination)
    try:
        repo = FinanceRepository(database)
        assert repo.list_transactions() == ([], 0)
        assert repo.transactions.history(ident) == history
        assert repo.transactions.restore(ident)["amount"] == 12.34
    finally:
        database.close()


def test_version_four_upgrade_preserves_existing_data_without_inventing_history(tmp_path, monkeypatch):
    import app.migrations as migrations

    path = tmp_path / "old.db"
    with monkeypatch.context() as historical:
        historical.setattr(migrations, "LATEST_SCHEMA_VERSION", 4)
        database = FinanceDatabase(path)
        with database.conn:
            database.conn.execute(
                """INSERT INTO transactions(date,type,category,amount,amount_cents,account_id)
                VALUES ('2026-01-01','income','Salary',12.34,1234,1)"""
            )
        database.close()
    database = FinanceDatabase(path)
    try:
        repo = FinanceRepository(database)
        entry = repo.list_transactions()[0][0]
        assert entry["amount"] == 12.34
        assert repo.transactions.history(entry["id"]) == {"items": [], "total": 0}
        assert repo.delete_transaction(entry["id"])
        assert repo.transactions.history(entry["id"])["items"][0]["before_state"]["amount_cents"] == 1234
    finally:
        database.close()


def test_audit_migration_failure_rolls_back_ddl_and_version(db):
    from .schema_helpers import remove_transaction_audit

    with db.conn:
        remove_transaction_audit(db.conn)

    def authorize(action, _arg1, _arg2, _database, _trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK

    db.conn.set_authorizer(authorize)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            migrate(db.conn)
    finally:
        db.conn.set_authorizer(None)
    assert db.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 4
    assert "deleted_at" not in [row["name"] for row in db.conn.execute("PRAGMA table_info(transactions)")]
    assert not db.conn.execute("SELECT name FROM sqlite_master WHERE name='transaction_audit'").fetchall()
    assert migrate(db.conn) == 5
