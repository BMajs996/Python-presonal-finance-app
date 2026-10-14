"""Query budgets and financial parity on both database engines."""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.database_errors import INTEGRITY_ERRORS
from app.domain import business_date
from app.domain.errors import Conflict
from app.migrations_query_indexes import INDEXES
from app.postgres_database import PostgresDatabase
from app.repositories.account_repository import AccountRepository
from app.repositories.budget_repository import BudgetRepository
from app.repositories.finance_repository import FinanceRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas import AccountCreate, BudgetCreate, CsvImport, RecurringCreate, TransactionCreate
from app.services.csv_import_service import CsvImportService

from .postgres_helpers import pg_url as pg_url


class CountingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def execute(self, statement, parameters=()):
        self.queries.append(statement)
        return self.connection.execute(statement, parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)


@pytest.fixture(params=["sqlite", "postgres"])
def repo(request, db):
    if request.param == "sqlite":
        yield db
    else:
        database = PostgresDatabase(request.getfixturevalue("pg_url"))
        try:
            yield FinanceRepository(database)
        finally:
            database.close()


def row(**changes):
    return TransactionCreate(
        **{
            "date": business_date.today(),
            "type": "expense",
            "category": "Food",
            "amount": "12.34",
            "description": "Lunch",
            **changes,
        }
    )


@pytest.mark.parametrize("account_id", [1, None])
def test_csv_maximum_preview_has_bounded_lookups(repo, account_id):
    connection = CountingConnection(repo.conn)
    service = CsvImportService(TransactionRepository(connection))
    rows = [row(account_id=account_id, description=f"Lunch {i}") for i in range(1000)]
    assert {item["status"] for item in service.preview(rows)["rows"]} == {"valid"}
    assert len(connection.queries) <= 12


def test_csv_maximum_commit_preserves_amounts_and_bounds_reads(repo):
    connection = CountingConnection(repo.conn)
    service = CsvImportService(TransactionRepository(connection))
    payload = CsvImport(batch_id=uuid4(), rows=[row(description=f"Lunch {i}") for i in range(1000)])
    assert service.commit(payload) == {"imported": 1000, "duplicates": 0}
    reads = [query for query in connection.queries if query.lstrip().startswith(("SELECT", "WITH"))]
    assert len(reads) <= 13
    assert repo.conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0] == 1234000
    assert repo.conn.execute("SELECT COUNT(*) FROM transaction_audit").fetchone()[0] == 1000
    assert service.commit(payload) == {"imported": 1000, "duplicates": 0}
    assert service.commit(payload.model_copy(update={"batch_id": uuid4()})) == {
        "imported": 0,
        "duplicates": 1000,
    }


def test_csv_batch_identity_and_invalid_account_are_preserved(repo):
    service = CsvImportService(repo.transactions)
    existing = repo.add_transaction(row(description="  LUNCH  "))
    removed = repo.add_transaction(row(description="Deleted"))
    repo.delete_transaction(removed["id"])
    rows = [
        row(description="lunch"),
        row(category="food"),
        row(description="Deleted"),
        row(account_id=99999),
        row(date=business_date.today() + timedelta(days=1)),
    ]
    assert [item["status"] for item in service.preview(rows)["rows"]] == [
        "duplicate",
        "valid",
        "valid",
        "invalid",
        "invalid",
    ]
    with pytest.raises(Conflict, match="Row 2"):
        service.commit(CsvImport(batch_id=uuid4(), rows=[row(description="New"), rows[3]]))
    assert repo.list_transactions()[1] == 1
    assert repo.get_transaction(existing["id"])["description"] == "LUNCH"


def test_csv_commit_preserves_backend_case_rules_for_new_rows(repo):
    first, second = "\u039f\u03a3", "\u039f\u03c3"
    assert first.lower() != second.lower()
    normalized = repo.conn.execute("SELECT lower(trim(?))", (first,)).fetchone()[0]
    expected = 1 if normalized == second.lower() else 2
    result = CsvImportService(repo.transactions).commit(
        CsvImport(batch_id=uuid4(), rows=[row(description=first), row(description=second)])
    )
    assert result == {"imported": expected, "duplicates": 2 - expected}


def test_database_failure_mid_import_rolls_back_rows_audit_and_receipt(repo):
    class FailThirdInsert(CountingConnection):
        inserts = 0
        fail = True

        def execute(self, statement, parameters=()):
            if statement.lstrip().startswith("INSERT INTO transactions("):
                self.inserts += 1
                if self.fail and self.inserts == 3:
                    parameters = list(parameters)
                    parameters[3:5] = [0, 0]
            return super().execute(statement, parameters)

    connection = FailThirdInsert(repo.conn)
    service = CsvImportService(TransactionRepository(connection))
    payload = CsvImport(batch_id=uuid4(), rows=[row(description=f"Row {i}") for i in range(3)])
    with pytest.raises(INTEGRITY_ERRORS):
        service.commit(payload)
    for table in ("transactions", "transaction_audit", "settings"):
        assert repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    connection.fail = False
    assert service.commit(payload) == {"imported": 3, "duplicates": 0}
    assert repo.conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0] == 3702
    assert repo.conn.execute("SELECT COUNT(*) FROM transaction_audit").fetchone()[0] == 3


def test_failed_auth_initialization_closes_database_and_pool(repo, monkeypatch):
    import sqlite3

    from app import main
    from fastapi.testclient import TestClient

    initialize = main.initialize_auth

    def fail(database):
        initialize(database)
        raise RuntimeError("synthetic auth initialization failure")

    monkeypatch.setattr(main, "open_database", lambda _settings: repo.database)
    monkeypatch.setattr(main, "initialize_auth", fail)
    with pytest.raises(RuntimeError, match="synthetic auth initialization"):
        with TestClient(main.app):
            pass
    if isinstance(repo.database, PostgresDatabase):
        assert repo.database.conn.raw.closed
        assert repo.database.pool.closed
    else:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            repo.conn.execute("SELECT 1")


def test_account_aggregate_excludes_unselected_history(db):
    inactive = db.add_account(AccountCreate(name="Archived"))
    db.deactivate_account(inactive["id"])
    today = business_date.today().isoformat()
    with db.conn:
        db.conn.executemany(
            "INSERT INTO transactions(date,type,category,amount,amount_cents,account_id) "
            "VALUES (?,'income','Test',1,100,?)",
            [(today, inactive["id"])] * 10000 + [(today, 1)] * 5,
        )
    visited = []

    class CountingSum:
        def __init__(self):
            self.total = 0

        def step(self, value):
            visited.append(value)
            self.total += value

        def finalize(self):
            return self.total

    db.conn.create_aggregate("SUM", 1, CountingSum)
    accounts = db.accounts.list()
    assert len(accounts) == 1
    assert accounts[0]["transaction_count"] == 5
    assert accounts[0]["balance"] == 5
    assert len(visited) == 5
    visited.clear()
    assert len(db.accounts.list(include_inactive=True)) == 2
    assert len(visited) == 10005
    visited.clear()
    assert db.accounts.get(1)["transaction_count"] == 5
    assert len(visited) == 5


def test_postgres_account_plan_aggregates_only_selected_accounts(pg_url):
    database = PostgresDatabase(pg_url)
    cutoff = business_date.today().isoformat()
    try:
        with database.conn.raw.transaction():
            database.conn.execute(
                "INSERT INTO accounts(id,name,type,currency,created_at,active) "
                "SELECT n,'Archived ' || n,'checking','USD','2026-01-01',0 "
                "FROM generate_series(2,100) n"
            )
            database.conn.execute(
                "INSERT INTO transactions(date,type,category,amount,amount_cents,account_id) "
                "SELECT ?,'income','Test',1,100,1+mod(n,100) FROM generate_series(1,10000) n",
                (cutoff,),
            )
        database.conn.execute("ANALYZE accounts")
        database.conn.execute("ANALYZE transactions")
        counter = CountingConnection(database.conn)
        accounts = AccountRepository(counter).list()
        assert len(accounts) == 1
        assert accounts[0]["transaction_count"] == 100
        plan = database.conn.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON) " + counter.queries[-1],
            (1, cutoff, cutoff, cutoff),
        ).fetchone()[0][0]["Plan"]

        def grouped_rows(node):
            rows = [node["Actual Rows"]] if node.get("Group Key") == ["t.account_id"] else []
            for child in node.get("Plans", []):
                rows.extend(grouped_rows(child))
            return rows

        assert grouped_rows(plan) == [1]
    finally:
        database.close()


def test_due_schedule_selection_is_bounded_and_eventually_processes_all(repo, monkeypatch):
    from app.repositories import recurring_repository

    monkeypatch.setattr(recurring_repository, "SCHEDULE_BATCH_SIZE", 2)
    today = business_date.today()
    for i in range(5):
        repo.add_recurring(
            RecurringCreate(
                type="expense",
                category=f"Due {i}",
                amount="1",
                frequency="daily",
                start_date=today - timedelta(days=1),
            )
        )
    assert [repo.recurring_transactions.process_due(through=today) for _ in range(4)] == [2, 2, 1, 0]
    assert repo.list_transactions()[1] == 5
    assert repo.conn.execute("SELECT COUNT(*) FROM recurring_occurrences").fetchone()[0] == 5


def test_query_indexes_are_installed(repo):
    if isinstance(repo.database, PostgresDatabase):
        names = {
            row[0]
            for row in repo.conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()"
            ).fetchall()
        }
    else:
        names = {
            row[0]
            for row in repo.conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    assert set(INDEXES) <= names


def test_budget_writes_only_read_the_affected_budget(repo):
    budgets = [
        repo.add_budget(BudgetCreate(category=f"Category {i}", monthly_limit="100")) for i in range(12)
    ]
    for budget in budgets:
        repo.add_transaction(row(category=budget["category"]))
    connection = CountingConnection(repo.conn)
    repository = BudgetRepository(connection)
    updated = repository.update(budgets[0]["id"], BudgetCreate(category="Category 0", monthly_limit="200"))
    assert updated["money"]["values"]["spent"] == "12.34"
    assert updated["monthly_limit"] == 200
    assert len(connection.queries) == 2
    assert "AND b.id=?" in connection.queries[-1]
    assert "user_id=b.user_id" not in connection.queries[-1]
    connection.queries.clear()
    upsert = repository.add(BudgetCreate(category="Category 0", monthly_limit="300"))
    assert upsert["id"] == budgets[0]["id"]
    assert len(connection.queries) == 2
    assert "AND b.id=?" in connection.queries[-1]
    connection.queries.clear()
    assert repository.update(99999, BudgetCreate(category="Missing", monthly_limit="1")) is None
    assert len(connection.queries) == 1


def test_targeted_budget_usage_avoids_unrelated_aggregation(db):
    budgets = [db.add_budget(BudgetCreate(category=f"Category {i}", monthly_limit="100")) for i in range(12)]
    for budget in budgets:
        for _ in range(20):
            db.add_transaction(row(category=budget["category"]))
    visited = []

    class CountingSum:
        def __init__(self):
            self.total = 0

        def step(self, value):
            if value is not None:
                visited.append(value)
                self.total += value

        def finalize(self):
            return self.total

    db.conn.create_aggregate("SUM", 1, CountingSum)
    assert len(db.budgets.usage()) == 12
    assert len(visited) == 240
    visited.clear()
    db.update_budget(budgets[0]["id"], BudgetCreate(category="Category 0", monthly_limit="200"))
    assert len(visited) == 20


def test_budget_deleted_before_update_response_remains_a_missing_result(repo, monkeypatch):
    budget = repo.add_budget(BudgetCreate(category="Food", monthly_limit="100"))
    usage = repo.budgets.usage

    def delete_before_read(budget_id):
        repo.budgets.delete(budget_id)
        return usage(budget_id)

    monkeypatch.setattr(repo.budgets, "usage", delete_before_read)
    assert repo.update_budget(budget["id"], BudgetCreate(category="Food", monthly_limit="200")) is None
    assert usage(budget["id"]) == []
