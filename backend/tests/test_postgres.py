import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier

import psycopg
import pytest
from app.core.config import settings
from app.domain.errors import Conflict
from app.main import app
from app.postgres_database import PostgresDatabase
from app.reconciliation_schemas import ClearedEntry, StatementCreate
from app.repositories.finance_repository import FinanceRepository
from app.repositories.reconciliation_repository import ReconciliationRepository
from app.schemas import AccountCreate, BudgetCreate, RecurringCreate, TransactionCreate, TransferCreate
from app.services.finance_service import FinanceService
from app.services.postgres_migration import transfer_sqlite
from app.services.reconciliation_service import ReconciliationService
from fastapi.testclient import TestClient
from pydantic import SecretStr

from . import test_api as api_cases
from . import test_financial_invariants as invariant_cases
from . import test_service_workflows as workflow_cases
from .postgres_helpers import pg_url as pg_url


@pytest.fixture
def pg_repo(pg_url):
    database = PostgresDatabase(pg_url)
    try:
        yield FinanceRepository(database)
    finally:
        database.close()


@pytest.mark.parametrize(
    "case",
    [
        invariant_cases.test_repository_persists_exact_cents,
        invariant_cases.test_base_currency_prevents_implicit_fx,
        workflow_cases.test_repository_missing_record_and_account_failure_paths,
    ],
)
def test_repository_parity(pg_repo, case):
    case(pg_repo)


@pytest.mark.parametrize(
    "case",
    [
        invariant_cases.test_income_minus_expenses_always_equals_net,
        invariant_cases.test_dashboard_period_and_comparisons_use_only_selected_days,
        invariant_cases.test_transfer_is_neutral_to_global_and_monthly_balance,
    ],
)
def test_financial_parity(pg_repo, case):
    case(pg_repo, FinanceService(pg_repo))


@pytest.mark.parametrize(
    "case",
    [
        workflow_cases.test_finance_service_transaction_and_budget_workflows,
        workflow_cases.test_finance_service_account_transfer_and_recurring_workflows,
    ],
)
def test_service_parity(pg_repo, case):
    case(FinanceService(pg_repo))


@pytest.mark.parametrize(
    "case",
    [
        api_cases.test_populated_response_contracts_preserve_service_payloads,
        api_cases.test_domain_errors_keep_detail_contract_and_status_codes,
        api_cases.test_duplicate_budget_update_returns_conflict_without_changing_budget,
        api_cases.test_transaction_recovery_and_history_api,
        api_cases.test_reconciliation_api_and_entry_locks,
    ],
)
def test_api_parity(pg_url, monkeypatch, case):
    monkeypatch.setattr(settings, "database_url", SecretStr(pg_url))
    from .conftest import login_client

    with TestClient(app) as client:
        login_client(client)
        case(client)


def test_concurrent_recurring_and_restore(pg_repo):
    pg_repo.add_recurring(
        RecurringCreate(
            type="expense",
            category="Rent",
            amount="10.25",
            frequency="daily",
            start_date=date.today() - timedelta(days=3),
        )
    )
    barrier = Barrier(3)

    def process():
        with pg_repo.database.connection() as connection:
            repository = FinanceRepository(pg_repo.database, connection=connection)
            barrier.wait(timeout=5)
            return repository.recurring_transactions.process_due()

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(process) for _ in range(3)]
        assert sum(future.result(timeout=15) for future in futures) == 3
    transaction = pg_repo.list_transactions()[0][0]
    pg_repo.delete_transaction(transaction["id"])

    def restore():
        with pg_repo.database.connection() as connection:
            repository = FinanceRepository(pg_repo.database, connection=connection)
            barrier.wait(timeout=5)
            return repository.transactions.restore(transaction["id"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(restore) for _ in range(3)]
        assert all(future.result(timeout=15)["id"] == transaction["id"] for future in futures)
    assert pg_repo.transactions.history(transaction["id"])["total"] == 3


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE transactions SET amount_cents=0,amount=0",
        "UPDATE transactions SET amount_cents=NULL",
        "UPDATE transactions SET amount=99.99",
        "DELETE FROM transaction_audit",
        "UPDATE transaction_audit SET actor='changed'",
        "DELETE FROM transactions",
    ],
)
def test_money_and_audit_guards(pg_repo, statement):
    transaction = pg_repo.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Salary",
            amount="12.34",
        )
    )
    with pytest.raises(psycopg.IntegrityError):
        with pg_repo.conn:
            pg_repo.conn.execute(statement)
    assert pg_repo.get_transaction(transaction["id"]) == transaction


def populate(db):
    first = db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Salary",
            amount="100",
        )
    )
    deleted = db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount="12.34",
        )
    )
    db.delete_transaction(deleted["id"])
    account = db.add_account(AccountCreate(name="Savings", opening_balance="-1.25"))
    db.add_transfer(
        TransferCreate(
            date=date.today(),
            from_account_id=1,
            to_account_id=account["id"],
            amount="25",
        )
    )
    db.add_budget(BudgetCreate(category="Food", monthly_limit="100"))
    db.add_recurring(
        RecurringCreate(
            type="income",
            category="Allowance",
            amount="0.10",
            frequency="daily",
            start_date=date.today() - timedelta(days=2),
        )
    )
    db.recurring_transactions.process_due()
    service = ReconciliationService(ReconciliationRepository(db.conn))
    draft = service.create(StatementCreate(account_id=1, closing_date=date.today(), closing_balance="100"))
    service.clear(draft["id"], ClearedEntry(kind="transaction", entry_id=first["id"], cleared=True))
    service.complete(draft["id"])
    return first, deleted, draft


def test_transfer_dry_run_commit_verification_and_rerun_refusal(pg_url, db):
    first, deleted, draft = populate(db)
    before = FinanceService(db).dashboard()
    history = db.transactions.history(deleted["id"])
    dry = transfer_sqlite(Path(db.database.db_path), pg_url, "USD")
    assert not dry["committed"]
    with psycopg.connect(pg_url) as connection:
        assert connection.execute("SELECT to_regclass('accounts')").fetchone()[0] is None

    copied = transfer_sqlite(Path(db.database.db_path), pg_url, "USD", commit=True)
    assert copied["committed"] and copied["verified_sha256"] == dry["verified_sha256"]
    assert Path(copied["source_backup"]).is_file()
    with pytest.raises(ValueError, match="empty"):
        transfer_sqlite(Path(db.database.db_path), pg_url, "USD")
    postgres = PostgresDatabase(pg_url)
    try:
        repo = FinanceRepository(postgres)
        assert FinanceService(repo).dashboard() == before
        assert FinanceService(repo).monthly_report() == FinanceService(db).monthly_report()
        assert repo.transactions.history(deleted["id"]) == history
        assert repo.transactions.restore(deleted["id"])["amount"] == 12.34
        with pytest.raises(psycopg.IntegrityError, match="Reconciliation:"):
            repo.delete_transaction(first["id"])
        service = ReconciliationService(ReconciliationRepository(repo.conn))
        assert service.detail(draft["id"])["difference_cents"] == 0
        with pytest.raises(Conflict):
            service.cancel(draft["id"])
        created = repo.add_transaction(
            TransactionCreate(
                date=date.today(),
                type="income",
                category="New",
                amount="0.20",
            )
        )
        assert created["id"] > max(row["id"] for row in db.list_transactions()[0])
    finally:
        postgres.close()


def test_failed_transfer_leaves_source_and_destination_unchanged(pg_url, db, monkeypatch):
    from pathlib import Path

    from app.services import postgres_migration

    populate(db)
    before = db.list_transactions()

    def fail(_connection):
        raise RuntimeError("injected verification failure")

    monkeypatch.setattr(postgres_migration, "install_guards", fail)
    with pytest.raises(RuntimeError, match="injected"):
        transfer_sqlite(Path(db.database.db_path), pg_url, "USD", commit=True)
    assert db.list_transactions() == before
    with psycopg.connect(pg_url) as connection:
        assert connection.execute("SELECT to_regclass('accounts')").fetchone()[0] is None


def test_transfer_blocks_source_writers(pg_url, db, monkeypatch):
    from app.services import postgres_migration

    original = postgres_migration.install_guards

    def check_lock(connection):
        with closing(sqlite3.connect(db.database.db_path, timeout=0)) as writer:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.execute("BEGIN IMMEDIATE")
        original(connection)

    monkeypatch.setattr(postgres_migration, "install_guards", check_lock)
    transfer_sqlite(Path(db.database.db_path), pg_url, "USD")
    with sqlite3.connect(db.database.db_path, timeout=0) as writer:
        writer.execute("BEGIN IMMEDIATE")


def test_transfer_rejects_future_schema(pg_url, db):
    with db.conn:
        db.conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (999, '2026-09-26')")
    with pytest.raises(ValueError, match="schema version"):
        transfer_sqlite(Path(db.database.db_path), pg_url, "USD")
    with psycopg.connect(pg_url) as connection:
        assert connection.execute("SELECT to_regclass('accounts')").fetchone()[0] is None


def test_transfer_discards_operational_sessions(pg_url, db):
    from app.services.auth_service import AuthService, initialize_auth

    from .conftest import TEST_PASSWORD

    initialize_auth(db.database)
    AuthService(db.database).login("owner", TEST_PASSWORD, None)
    result = transfer_sqlite(Path(db.database.db_path), pg_url, "USD", commit=True)
    assert "auth_sessions" not in result["counts"]
    postgres = PostgresDatabase(pg_url)
    try:
        initialize_auth(postgres)
        with postgres.connection() as connection:
            assert connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
    finally:
        postgres.close()
