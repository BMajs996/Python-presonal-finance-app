from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import pytest
from app.database import FinanceDatabase
from app.domain.errors import Conflict, InvalidOperation
from app.postgres_database import PostgresDatabase
from app.repositories.account_repository import AccountRepository
from app.repositories.recurring_repository import RecurringRepository
from app.schemas import AccountCreate, RecurringCreate, RecurringUpdate

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    database = (
        FinanceDatabase(tmp_path / "inactive.db")
        if request.param == "sqlite"
        else PostgresDatabase(request.getfixturevalue("pg_url"))
    )
    try:
        yield database
    finally:
        database.close()


def account(database):
    return AccountRepository(database.conn).add(AccountCreate(name="Private account"))["id"]


def schedule(connection, account_id):
    return RecurringRepository(connection).add(
        RecurringCreate(
            account_id=account_id,
            type="expense",
            category="Private category",
            amount="12.34",
            description="Sensitive description",
            frequency="daily",
            start_date=date(2026, 1, 1),
        )
    )


def test_deactivation_requires_pausing_or_moving_every_active_schedule(database):
    ident = account(database)
    recurring = RecurringRepository(database.conn)
    first = schedule(database.conn, ident)
    second = schedule(database.conn, ident)
    accounts = AccountRepository(database.conn)
    with pytest.raises(Conflict, match="Pause or move"):
        accounts.deactivate(ident)
    assert accounts.get(ident)["active"] == 1
    recurring.deactivate(first["id"])
    with pytest.raises(Conflict):
        accounts.deactivate(ident)
    target = accounts.default_account_id()
    recurring.update(
        second["id"],
        RecurringUpdate(
            account_id=target,
            type="expense",
            category="Moved",
            amount="12.34",
            frequency="daily",
            next_date=date(2026, 1, 2),
        ),
    )
    accounts.deactivate(ident)
    assert accounts.get(ident)["active"] == 0
    assert recurring.get(first["id"])["account_id"] == ident
    assert recurring.get(second["id"])["account_id"] == target


@pytest.mark.parametrize("missing_account", [False, True])
def test_legacy_invalid_schedule_is_paused_without_entries_or_reassignment(database, caplog, missing_account):
    ident = account(database)
    broken = schedule(database.conn, ident)
    # Simulate data predating the guard, including an orphan with a null reference.
    with database.conn:
        if missing_account:
            database.conn.execute(
                "UPDATE recurring_transactions SET account_id=NULL WHERE id=?", (broken["id"],)
            )
        else:
            database.conn.execute("UPDATE accounts SET active=0 WHERE id=?", (ident,))
    repository = RecurringRepository(database.conn)
    with caplog.at_level("WARNING"):
        assert repository.process_due(date(2026, 1, 3)) == 0
        assert repository.process_due(date(2026, 1, 3)) == 0
    row = database.conn.execute("SELECT * FROM recurring_transactions WHERE id=?", (broken["id"],)).fetchone()
    assert row["active"] == 0
    assert row["next_date"] == broken["next_date"]
    assert row["account_id"] == (None if missing_account else ident)
    for table in ("transactions", "recurring_occurrences", "transaction_audit"):
        assert database.conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
    warnings = [
        record.getMessage() for record in caplog.records if "Pausing recurring schedule" in record.message
    ]
    assert len(warnings) == 1
    assert f"id={broken['id']}" in warnings[0]
    assert "owner review required" in warnings[0]
    for secret in ("Private account", "Private category", "Sensitive description", "12.34"):
        assert secret not in warnings[0]


def test_invalid_schedule_does_not_stop_valid_work(database):
    ident = account(database)
    broken = schedule(database.conn, ident)
    healthy_account = AccountRepository(database.conn).default_account_id()
    healthy = schedule(database.conn, healthy_account)
    with database.conn:
        database.conn.execute("UPDATE accounts SET active=0 WHERE id=?", (ident,))
    recurring = RecurringRepository(database.conn)
    assert recurring.process_due(date(2026, 1, 3)) == 2
    assert recurring.get(broken["id"])["active"] == 0
    assert recurring.get(healthy["id"])["next_date"] == "2026-01-04"
    assert [row[0] for row in database.conn.execute("SELECT account_id FROM transactions")] == [
        healthy_account,
        healthy_account,
    ]


def ordered_race(database, first, second):
    locked, attempting, release = Event(), Event(), Event()

    class GatedConnection:
        def __init__(self, connection, hold):
            self.connection = connection
            self.hold = hold

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, params=()):
            reservation = sql.strip().upper() == "BEGIN IMMEDIATE"
            if reservation and not self.hold:
                attempting.set()
            cursor = self.connection.execute(sql, params)
            if reservation and self.hold:
                locked.set()
                assert release.wait(5)
            return cursor

    def run(action, hold):
        with database.connection() as connection:
            return action(GatedConnection(connection, hold))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(run, first, True)
        try:
            assert locked.wait(5)
            second_result = pool.submit(run, second, False)
            assert attempting.wait(5)
        finally:
            release.set()
        return first_result.result(timeout=10), second_result.result(timeout=10)


@pytest.mark.parametrize("worker_first", [False, True])
def test_worker_and_deactivation_share_the_same_writer_reservation(database, worker_first):
    ident = account(database)
    schedule(database.conn, ident)

    def worker(connection):
        return RecurringRepository(connection).process_due(date(2026, 1, 3))

    def deactivate(connection):
        with pytest.raises(Conflict):
            AccountRepository(connection).deactivate(ident)
        return "conflict"

    actions = (worker, deactivate) if worker_first else (deactivate, worker)
    results = ordered_race(database, *actions)
    assert results == ((2, "conflict") if worker_first else ("conflict", 2))
    assert AccountRepository(database.conn).get(ident)["active"] == 1
    assert (
        database.conn.execute("SELECT COUNT(*) FROM transactions WHERE account_id=?", (ident,)).fetchone()[0]
        == 2
    )


@pytest.mark.parametrize("operation", ["create", "move"])
def test_schedule_write_rechecks_account_after_concurrent_deactivation(database, operation):
    ident = account(database)
    existing = schedule(database.conn, AccountRepository(database.conn).default_account_id())

    def deactivate(connection):
        AccountRepository(connection).deactivate(ident)

    def write(connection):
        with pytest.raises(InvalidOperation, match="inactive"):
            if operation == "create":
                schedule(connection, ident)
            else:
                RecurringRepository(connection).update(
                    existing["id"],
                    RecurringUpdate(
                        account_id=ident,
                        type="expense",
                        category="Moved",
                        amount="12.34",
                        frequency="daily",
                        next_date=date(2026, 1, 2),
                    ),
                )

    ordered_race(database, deactivate, write)
    assert (
        database.conn.execute(
            "SELECT COUNT(*) FROM recurring_transactions WHERE account_id=? AND active=1", (ident,)
        ).fetchone()[0]
        == 0
    )
    assert RecurringRepository(database.conn).get(existing["id"])["account_id"] != ident


def test_api_deactivation_conflict_is_controlled_and_pause_allows_retry(raw_client):
    login_client(raw_client)
    ident = raw_client.post("/api/accounts", json={"name": "Scheduled account"}).json()["id"]
    response = raw_client.post(
        "/api/recurring",
        json={
            "account_id": ident,
            "type": "expense",
            "category": "Future",
            "amount": "10",
            "frequency": "monthly",
            "start_date": "2099-01-01",
        },
    )
    assert response.status_code == 201
    schedule_id = response.json()["id"]
    response = raw_client.delete(f"/api/accounts/{ident}")
    assert response.status_code == 409
    assert response.json() == {
        "detail": "Pause or move active recurring schedules before deactivating this account"
    }
    assert any(row["id"] == ident for row in raw_client.get("/api/accounts").json())
    assert raw_client.delete(f"/api/recurring/{schedule_id}").status_code == 204
    assert raw_client.delete(f"/api/accounts/{ident}").status_code == 204
