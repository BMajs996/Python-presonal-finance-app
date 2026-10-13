import sqlite3
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from app.database import FinanceDatabase
from app.domain import business_date
from app.domain.date_range import DateRange
from app.domain.errors import NotFound
from app.postgres_database import PostgresDatabase
from app.reconciliation_schemas import StatementCreate
from app.repositories.finance_repository import FinanceRepository
from app.repositories.reconciliation_repository import ReconciliationRepository
from app.schemas import AccountCreate, BudgetCreate, RecurringCreate, TransactionCreate, TransferCreate
from app.services.csv_import_service import CsvImportService
from app.services.reconciliation_service import ReconciliationService
from app.services.recurring_runner import process_recurring
from app.user_schemas import RegistrationContacts
from pydantic import ValidationError

from .postgres_helpers import pg_url as pg_url


@pytest.fixture(params=["sqlite", "postgres"])
def owners(request, tmp_path):
    database = (
        PostgresDatabase(request.getfixturevalue("pg_url"))
        if request.param == "postgres"
        else FinanceDatabase(tmp_path / "owners.db")
    )
    try:
        with database.conn:
            database.conn.execute(
                "INSERT INTO users(id,email,email_key,phone) VALUES (2,?,?,?)",
                ("second@example.com", "second@example.com", "+381641234567"),
            )
        from app.repositories.account_repository import AccountRepository

        AccountRepository(database.conn, user_id=2).add(AccountCreate(name="Main Account"))
        yield (FinanceRepository(database, user_id=1), FinanceRepository(database, user_id=2))
    finally:
        database.close()


def transaction(repo, category="Food", amount="12.34"):
    return repo.add_transaction(
        TransactionCreate(
            date=business_date.today(),
            type="expense",
            category=category,
            amount=amount,
            description="Private entry",
        )
    )


def test_reads_reports_budgets_and_history_are_owner_scoped(owners):
    first, second = owners
    own, foreign = transaction(first), transaction(second, "Other private category", "99.99")
    for repo in owners:
        repo.add_budget(BudgetCreate(category="Food", monthly_limit="100"))
    assert len(first.list_accounts()) == len(second.list_accounts()) == 1
    assert first.list_accounts()[0]["id"] != second.list_accounts()[0]["id"]
    assert first.list_transactions()[1] == second.list_transactions()[1] == 1
    assert first.categories() == ["Food"]
    assert second.categories() == ["Other private category"]
    assert first.get_transaction(foreign["id"]) is None
    assert first.balances.total_cents() == -1234
    period = DateRange.trailing(7, end=business_date.today())
    assert first.reports.dashboard_data(period)["money"]["values"]["expenses"] == "12.34"
    assert first.get_budget_usage()[0]["money"]["values"]["spent"] == "12.34"
    assert second.get_budget_usage()[0]["money"]["values"]["spent"] == "0.00"
    assert first.reports.monthly_data()["summary"]["money"]["values"]["expenses"] == "12.34"
    assert first.balances.daily_history_cents(period)[1][0]["change_cents"] == -1234
    with pytest.raises(NotFound):
        first.transactions.history(foreign["id"])
    assert first.transactions.history(own["id"])["total"] == 1


def test_mutations_restore_and_foreign_accounts_cannot_cross_owners(owners):
    first, second = owners
    foreign = transaction(second)
    payload = TransactionCreate(date=business_date.today(), type="income", category="Salary", amount="10")
    assert first.transactions.update(foreign["id"], payload) is None
    assert not first.transactions.delete(foreign["id"])
    second.delete_transaction(foreign["id"])
    assert first.transactions.list(deleted=True)[1] == 0
    with pytest.raises(NotFound):
        first.transactions.restore(foreign["id"])
    for action in (
        first.accounts.deactivate,
        first.accounts.account_currency,
        first.accounts.resolve_account_id,
    ):
        with pytest.raises(NotFound):
            action(second.accounts.default_account_id())
    payload.account_id = second.accounts.default_account_id()
    with pytest.raises(NotFound):
        first.add_transaction(payload)
    assert second.transactions.list(deleted=True)[1] == 1


def test_transfer_and_budget_mutations_are_scoped(owners):
    first, second = owners
    target = second.add_account(AccountCreate(name="Savings"))
    foreign = second.add_transfer(
        TransferCreate(
            date=business_date.today(),
            from_account_id=second.accounts.default_account_id(),
            to_account_id=target["id"],
            amount="10",
        )
    )
    assert first.list_transfers() == []
    assert first.get_transfer(foreign["id"]) is None
    first.delete_transfer(foreign["id"])
    assert second.get_transfer(foreign["id"]) is not None
    with pytest.raises(NotFound):
        first.add_transfer(
            TransferCreate(
                date=business_date.today(),
                from_account_id=first.accounts.default_account_id(),
                to_account_id=target["id"],
                amount="10",
            )
        )
    budget = second.add_budget(BudgetCreate(category="Food", monthly_limit="20"))
    assert first.update_budget(budget["id"], BudgetCreate(category="Food", monthly_limit="30")) is None
    first.delete_budget(budget["id"])
    assert second.get_budget_usage()[0]["id"] == budget["id"]


def test_csv_accounts_duplicates_and_retry_receipts_are_scoped(owners):
    from app.schemas import CsvImport

    first, second = owners
    row = TransactionCreate(date=business_date.today(), type="expense", category="Food", amount="12.34")
    batch = CsvImport(batch_id=uuid4(), rows=[row])
    for repo in owners:
        service = CsvImportService(repo.transactions)
        assert service.preview([row])["rows"][0]["status"] == "valid"
        assert service.commit(batch)["imported"] == 1
        assert service.commit(batch)["imported"] == 1
        assert repo.list_transactions()[1] == 1
    row.account_id = second.accounts.default_account_id()
    assert CsvImportService(first.transactions).preview([row])["rows"][0]["status"] == "invalid"


def test_recurring_worker_preserves_owner_and_skips_disabled_users(owners):
    first, second = owners
    today = business_date.today()
    schedules = []
    for repo in owners:
        schedules.append(
            repo.add_recurring(
                RecurringCreate(
                    type="income",
                    category="Allowance",
                    amount="5",
                    frequency="daily",
                    start_date=today - timedelta(days=1),
                )
            )
        )
    assert first.recurring_transactions.get(schedules[1]["id"]) is None
    first.delete_recurring(schedules[1]["id"])
    assert second.recurring_transactions.get(schedules[1]["id"])["active"] == 1
    assert first.recurring_transactions.process_due() == 1
    assert second.list_transactions()[1] == 0
    assert process_recurring(first.database) == 1
    assert second.list_transactions()[1] == 1
    with first.conn:
        first.conn.execute("UPDATE users SET active=0 WHERE id=2")
        first.conn.execute(
            "UPDATE recurring_transactions SET next_date=? WHERE id=?",
            (today.isoformat(), schedules[1]["id"]),
        )
    assert process_recurring(first.database) == 0


def test_statements_and_entries_are_scoped(owners):
    first, second = owners
    own, foreign = transaction(first), transaction(second)
    repositories = [ReconciliationRepository(repo.conn, user_id=repo.user_id) for repo in owners]
    statements = [
        ReconciliationService(repo).create(
            StatementCreate(
                account_id=repo.default_account_id(),
                closing_date=business_date.today(),
                closing_balance="-12.34",
            )
        )
        for repo in repositories
    ]
    repo = repositories[0]
    assert repo.list(repositories[1].default_account_id()) == []
    for action in (repo.get, repo.complete, repo.cancel):
        with pytest.raises(NotFound):
            action(statements[1]["id"])
    with pytest.raises(NotFound):
        repo.entries(statements[1])
    with pytest.raises(NotFound):
        repo.clear(statements[0], "transaction", foreign["id"], True)
    assert repo.eligible(statements[0], "transaction", own["id"])


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE accounts SET user_id=2 WHERE user_id=1",
        "UPDATE transactions SET account_id=(SELECT id FROM accounts WHERE user_id=2) WHERE id=?",
        "UPDATE recurring_transactions SET account_id=NULL WHERE id=?",
        "DELETE FROM accounts WHERE user_id=1",
    ],
)
def test_database_rejects_ownership_reassignment_and_orphans(owners, sql):
    first, _second = owners
    item = transaction(first)
    recurring = first.add_recurring(
        RecurringCreate(
            type="income",
            category="Allowance",
            amount="5",
            frequency="daily",
            start_date=business_date.today(),
        )
    )
    params = (recurring["id"] if "recurring" in sql else item["id"],) if "?" in sql else ()
    with pytest.raises((sqlite3.IntegrityError, psycopg.errors.CheckViolation)):
        with first.conn:
            first.conn.execute(sql, params)
    assert first.get_transaction(item["id"]) == item
    assert first.accounts.get(first.accounts.default_account_id()) is not None


def test_contact_validation_and_unverified_notification_defaults(owners):
    first, _second = owners
    contacts = RegistrationContacts(email=" Owner@EXAMPLE.COM ", phone=" +381641234567 ")
    assert str(contacts.email) == "Owner@example.com"
    assert contacts.email_key == "owner@example.com"
    assert contacts.phone == "+381641234567"
    row = first.conn.execute("SELECT * FROM users WHERE id=2").fetchone()
    for name in ("email_verified_at", "phone_verified_at"):
        assert row[name] is None
    for name in ("email_notifications", "sms_notifications", "monthly_reports"):
        assert row[name] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "phone": "+381641234567"},
        {"email": "owner@example.com", "phone": "0641234567"},
        {"email": "owner@example.com", "phone": "+1234567890123456"},
        {"email": "owner@example.com", "phone": "+01234567"},
        {"email": "owner@example.com", "phone": "+381641234567", "email_verified_at": "now"},
        {"email": "owner@example.com"},
    ],
)
def test_registration_contacts_reject_invalid_or_privileged_input(payload):
    with pytest.raises(ValidationError):
        RegistrationContacts.model_validate(payload)


def test_http_uses_session_owner_for_csv_reports_and_mutations(owners, monkeypatch):
    from app.core.config import settings
    from app.main import app
    from app.services.auth_service import AuthService
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from .conftest import login_client

    first, second = owners
    database = first.database
    if isinstance(database, PostgresDatabase):
        monkeypatch.setattr(settings, "database_url", SecretStr(database._url))
    else:
        monkeypatch.setattr(settings, "database_path", database.db_path)
    original = AuthService.session
    acting_user = [1]

    # Phase 1 has no second-user login yet; inject an authenticated principal at the session boundary.
    def session(service, token):
        result = original(service, token)
        return {**result, "user_id": acting_user[0], "is_admin": acting_user[0] == 1} if result else None

    monkeypatch.setattr(AuthService, "session", session)
    foreign = transaction(second)
    with TestClient(app) as client:
        login_client(client)
        assert client.get("/api/transactions").json()["total"] == 0
        assert client.get(f"/api/transactions/{foreign['id']}/history").status_code == 404
        assert client.delete(f"/api/transactions/{foreign['id']}").status_code == 404
        row = {
            "date": business_date.today().isoformat(),
            "type": "expense",
            "category": "Food",
            "amount": "12.34",
        }
        batch = {"batch_id": str(uuid4()), "rows": [row]}
        assert client.post("/api/transactions/import", json=batch).json()["imported"] == 1
        acting_user[0] = 2
        assert client.get("/api/transactions").json()["total"] == 1
        assert client.get("/api/operations/health").status_code == 403
        assert client.post("/api/transactions/import", json=batch).json()["imported"] == 1
        assert client.get("/api/transactions").json()["total"] == 2
        row["account_id"] = first.accounts.default_account_id()
        assert client.post("/api/transactions", json=row).status_code == 404
        assert (
            client.post("/api/transactions/import/preview", json={"rows": [row]}).json()["rows"][0]["status"]
            == "invalid"
        )
        row.pop("account_id")
        row["user_id"] = 1
        response = client.post("/api/transactions", json=row)
        assert response.status_code == 201
        assert response.json()["account_id"] == second.accounts.default_account_id()
        assert client.get("/api/dashboard").json()["money"]["values"]["expenses"] == "37.02"
        assert (
            client.post(
                "/api/auth/register", json={"email": "new@example.com", "phone": "+381641234567"}
            ).status_code
            == 422
        )


def test_parallel_requests_and_reused_connections_keep_explicit_owner(owners):
    from concurrent.futures import ThreadPoolExecutor

    database = owners[0].database
    batch_id = uuid4()
    from app.schemas import CsvImport

    def save(user_id):
        with database.connection() as connection:
            repo = FinanceRepository(database, connection=connection, user_id=user_id)
            row = TransactionCreate(
                date=business_date.today(), type="income", category="Salary", amount="1.23"
            )
            return CsvImportService(repo.transactions).commit(CsvImport(batch_id=batch_id, rows=[row]))

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(save, user_id) for user_id in (1, 2)]
        assert [future.result(timeout=15)["imported"] for future in futures] == [1, 1]
    for user_id in (2, 1, 2, 1):
        with database.connection() as connection:
            repo = FinanceRepository(database, connection=connection, user_id=user_id)
            items, total = repo.list_transactions()
            assert total == 1
            assert items[0]["account_id"] == repo.accounts.default_account_id()
            assert repo.balances.total_cents() == 123


def test_database_rejects_cross_owner_transfers_and_budget_moves(owners):
    first, second = owners
    one = first.accounts.default_account_id()
    two = second.accounts.default_account_id()
    own_target = first.add_account(AccountCreate(name="Savings"))["id"]
    foreign_target = second.add_account(AccountCreate(name="Savings"))["id"]
    transfer = first.add_transfer(
        TransferCreate(date=business_date.today(), from_account_id=one, to_account_id=own_target, amount="1")
    )
    budget = first.add_budget(BudgetCreate(category="Food", monthly_limit="10"))
    statements = [
        (
            "INSERT INTO transfers(date,from_account_id,to_account_id,amount,amount_cents,created_at) "
            "VALUES (?,?,?,1,100,'test')",
            (business_date.today().isoformat(), one, two),
        ),
        (
            "UPDATE transfers SET from_account_id=?,to_account_id=? WHERE id=?",
            (two, foreign_target, transfer["id"]),
        ),
        ("UPDATE budgets SET user_id=2 WHERE id=?", (budget["id"],)),
    ]
    for query, params in statements:
        with pytest.raises((sqlite3.IntegrityError, psycopg.errors.CheckViolation)):
            with first.conn:
                first.conn.execute(query, params)
    assert first.get_transfer(transfer["id"]) == transfer
    assert first.get_budget_usage()[0]["id"] == budget["id"]


@pytest.mark.parametrize("user_id", [None, 0, -1, True, "1"])
def test_invalid_owner_context_is_rejected(owners, user_id):
    from app.repositories.account_repository import AccountRepository

    with pytest.raises(ValueError, match="financial owner"):
        AccountRepository(owners[0].conn, user_id=user_id)


def test_scoped_recurring_selection_rejects_oversized_batch_and_empty_is_noop(owners):
    repo = owners[0].recurring_transactions
    assert repo.process_due(schedule_ids=[]) == 0
    with pytest.raises(ValueError, match="batch limit"):
        repo.process_due(schedule_ids=list(range(101)))


def test_disabled_bootstrap_owner_cannot_sign_in_or_use_existing_session(owners):
    from app.services.auth_service import AuthService, initialize_auth
    from fastapi import HTTPException

    from .conftest import TEST_PASSWORD

    database = owners[0].database
    initialize_auth(database)
    service = AuthService(database)
    token, _csrf = service.login("owner", TEST_PASSWORD, None)
    assert service.session(token)["user_id"] == 1
    with database.conn:
        database.conn.execute("UPDATE users SET active=0 WHERE id=1")
    assert service.session(token) is None
    with pytest.raises(HTTPException) as error:
        service.login("owner", TEST_PASSWORD, None)
    assert error.value.status_code == 401


def test_financial_facade_rejects_owner_without_a_default_account(owners):
    with pytest.raises(NotFound):
        FinanceRepository(owners[0].database, user_id=999)
