import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from app.database import FinanceDatabase
from app.domain.errors import Conflict, InvalidOperation, NotFound
from app.migrations import migrate
from app.reconciliation_schemas import ClearedEntry, StatementCreate
from app.repositories.reconciliation_repository import ReconciliationRepository
from app.schemas import AccountCreate, TransactionCreate, TransferCreate
from app.services.backup_service import BackupService
from app.services.reconciliation_service import ReconciliationService

from .schema_helpers import remove_reconciliation


@pytest.fixture
def service(db):
    return ReconciliationService(ReconciliationRepository(db.conn))


def entry(db, amount="12.34", **changes):
    return db.add_transaction(
        TransactionCreate(
            **{
                "date": date.today(),
                "type": "income",
                "category": "Salary",
                "amount": amount,
                **changes,
            }
        )
    )


def start(service, balance="0", account_id=1, closing_date=None):
    return service.create(
        StatementCreate(
            account_id=account_id,
            closing_date=closing_date or date.today(),
            closing_balance=balance,
        )
    )


def clear(service, statement, ident, kind="transaction", cleared=True):
    return service.clear(statement["id"], ClearedEntry(kind=kind, entry_id=ident, cleared=cleared))


def test_exact_totals_completion_and_read_only_history(db, service):
    income = entry(db, "0.30")
    expense = entry(db, "0.10", type="expense")
    draft = start(service, "0.20")
    assert draft["difference_cents"] == 20
    with pytest.raises(Conflict, match="zero"):
        service.complete(draft["id"])
    clear(service, draft, income["id"])
    result = clear(service, draft, expense["id"])
    assert result["cleared_balance_cents"] == 20
    assert result["difference_cents"] == 0
    completed = service.complete(draft["id"])
    assert completed["status"] == "completed" and completed["completed_at"]
    assert service.complete(draft["id"]) == completed
    assert service.list(1)[0]["status"] == "completed"
    with pytest.raises(Conflict):
        clear(service, draft, income["id"], cleared=False)
    with pytest.raises(Conflict):
        service.cancel(draft["id"])
    assert db.get_account(1)["balance"] == 0.20


def test_draft_persists_and_unchecking_or_cancellation_unlocks(db, service):
    transaction = entry(db)
    draft = start(service, "12.34")
    clear(service, draft, transaction["id"])
    clear(service, draft, transaction["id"])
    with db.database.connection() as conn:
        another = ReconciliationService(ReconciliationRepository(conn))
        assert another.detail(draft["id"])["entries"][0]["cleared"]
    with pytest.raises(sqlite3.IntegrityError, match="Reconciliation:"):
        db.delete_transaction(transaction["id"])
    clear(service, draft, transaction["id"], cleared=False)
    assert db.delete_transaction(transaction["id"])
    db.transactions.restore(transaction["id"])
    clear(service, draft, transaction["id"])
    service.cancel(draft["id"])
    assert service.list(1) == []
    assert db.delete_transaction(transaction["id"])


def test_transfer_clears_independently_on_both_accounts(db, service):
    savings = db.add_account(AccountCreate(name="Savings", opening_balance="100"))
    transfer = db.add_transfer(
        TransferCreate(
            date=date.today(),
            from_account_id=savings["id"],
            to_account_id=1,
            amount="25",
        )
    )
    outgoing = start(service, "75", savings["id"])
    incoming = start(service, "25", 1)
    assert outgoing["entries"][0]["amount_cents"] == -2500
    assert incoming["entries"][0]["amount_cents"] == 2500
    clear(service, outgoing, transfer["id"], "transfer")
    assert not service.detail(incoming["id"])["entries"][0]["cleared"]
    service.complete(outgoing["id"])
    with pytest.raises(sqlite3.IntegrityError, match="Reconciliation:"):
        db.delete_transfer(transfer["id"])
    clear(service, incoming, transfer["id"], "transfer")
    service.complete(incoming["id"])
    assert sum(a["balance"] for a in db.list_accounts()) == 100


def test_outstanding_older_entries_carry_forward_without_double_counting(db, service):
    yesterday = date.today() - timedelta(days=1)
    first = entry(db, "10", date=yesterday)
    outstanding = entry(db, "2", date=yesterday)
    draft = start(service, "10", closing_date=yesterday)
    clear(service, draft, first["id"])
    service.complete(draft["id"])
    today = start(service, "12")
    assert today["opening_balance_cents"] == 1000
    assert [r["entry_id"] for r in today["entries"]] == [outstanding["id"]]
    clear(service, today, outstanding["id"])
    assert service.complete(today["id"])["cleared_balance_cents"] == 1200


def test_deleted_future_and_other_account_entries_are_ineligible(db, service):
    removed = entry(db)
    db.delete_transaction(removed["id"])
    future = entry(db, date=date.today() + timedelta(days=1))
    other_account = db.add_account(AccountCreate(name="Other"))
    other = entry(db, account_id=other_account["id"])
    draft = start(service)
    assert draft["entries"] == []
    for transaction in (removed, future, other):
        with pytest.raises(NotFound):
            clear(service, draft, transaction["id"])


def test_negative_opening_and_empty_statement(db, service):
    account = db.add_account(AccountCreate(name="Credit", opening_balance="-12.34"))
    draft = start(service, "-12.34", account["id"])
    assert draft["difference_cents"] == 0
    assert service.complete(draft["id"])["entries"] == []


def test_dates_duplicate_drafts_and_inactive_accounts(db, service):
    with pytest.raises(InvalidOperation, match="future"):
        start(service, closing_date=date.today() + timedelta(days=1))
    draft = start(service)
    with pytest.raises(Conflict, match="already"):
        start(service)
    service.complete(draft["id"])
    for day in (date.today(), date.today() - timedelta(days=1)):
        with pytest.raises(InvalidOperation, match="after"):
            start(service, closing_date=day)
    account = db.add_account(AccountCreate(name="Inactive"))
    pending = start(service, account_id=account["id"])
    db.deactivate_account(account["id"])
    with pytest.raises(InvalidOperation):
        service.complete(pending["id"])
    service.cancel(pending["id"])
    with pytest.raises(InvalidOperation):
        start(service, account_id=account["id"])


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE transactions SET amount=20, amount_cents=2000",
        "UPDATE transactions SET date='2026-01-01'",
        "UPDATE transactions SET account_id=2",
        "UPDATE transactions SET deleted_at='2026-01-01'",
        "UPDATE accounts SET opening_balance=10, opening_balance_cents=1000 WHERE id=1",
        "DELETE FROM reconciliation_entries",
        "UPDATE reconciliation_entries SET account_id=2",
        "DELETE FROM reconciliations",
        "UPDATE reconciliations SET status='draft'",
    ],
)
def test_completed_evidence_cannot_be_mutated_with_direct_sql(db, service, sql):
    transaction = entry(db)
    draft = start(service, "12.34")
    clear(service, draft, transaction["id"])
    before = service.complete(draft["id"])
    with pytest.raises(sqlite3.IntegrityError):
        with db.conn:
            db.conn.execute(sql)
    assert service.detail(draft["id"]) == before


def test_concurrent_completion_is_idempotent(db, service):
    transaction = entry(db)
    draft = start(service, "12.34")
    clear(service, draft, transaction["id"])
    barrier = Barrier(3)

    def complete():
        with db.database.connection() as conn:
            worker = ReconciliationService(ReconciliationRepository(conn))
            barrier.wait(timeout=5)
            return worker.complete(draft["id"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(complete) for _ in range(3)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1] == results[2]
    assert len(service.list(1)) == 1


def test_completion_failure_rolls_back_and_remains_retryable(db, service):
    draft = start(service)
    db.conn.execute("""CREATE TRIGGER fail_completion BEFORE UPDATE ON reconciliations
        BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        service.complete(draft["id"])
    assert service.detail(draft["id"])["status"] == "draft"
    db.conn.execute("DROP TRIGGER fail_completion")
    assert service.complete(draft["id"])["status"] == "completed"


def test_migration_preserves_money_and_rolls_back_partial_ddl(db):
    before = entry(db)
    with db.conn:
        remove_reconciliation(db.conn)

    def authorize(action, _arg1, _arg2, _database, _trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK

    db.conn.set_authorizer(authorize)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            migrate(db.conn)
    finally:
        db.conn.set_authorizer(None)
    assert db.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 5
    assert not db.conn.execute("SELECT name FROM sqlite_master WHERE name='reconciliations'").fetchall()
    assert migrate(db.conn) == 6
    assert migrate(db.conn) == 6
    assert db.get_transaction(before["id"]) == before
    assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_backup_preserves_statement_and_locks(db, service, tmp_path):
    transaction = entry(db)
    draft = start(service, "12.34")
    clear(service, draft, transaction["id"])
    before = service.complete(draft["id"])
    archive = BackupService(db.database.db_path).create_backup(tmp_path / "statement.financebackup")
    destination = tmp_path / "restored.db"
    BackupService(destination).restore_backup(archive)
    restored = FinanceDatabase(destination)
    try:
        restored_service = ReconciliationService(ReconciliationRepository(restored.conn))
        assert restored_service.detail(draft["id"]) == before
        with pytest.raises(sqlite3.IntegrityError):
            with restored.conn:
                restored.conn.execute("UPDATE transactions SET description='changed'")
    finally:
        restored.close()
