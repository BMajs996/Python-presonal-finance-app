import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from app.maintenance import main
from app.migrations import migrate
from app.repositories.recurring_repository import RecurringRepository
from app.schemas import RecurringCreate
from app.services import recurring_runner


def add_schedule(db):
    return db.add_recurring(
        RecurringCreate(
            type="expense",
            category="Rent",
            amount="10.25",
            description="Rent",
            frequency="monthly",
            start_date=date(2026, 1, 1),
        )
    )


def test_retry_rewind_and_deleted_transactions_do_not_recreate_occurrences(db):
    schedule = add_schedule(db)
    repository = db.recurring_transactions
    through = date(2026, 4, 1)
    assert repository.process_due(through) == 3
    assert repository.process_due(through) == 0
    transaction = db.list_transactions()[0][0]
    db.delete_transaction(transaction["id"])
    with db.database.conn:
        db.database.conn.execute(
            "UPDATE recurring_transactions SET next_date=? WHERE id=?",
            ("2026-02-01", schedule["id"]),
        )
    assert repository.process_due(through) == 0
    assert db.list_transactions()[1] == 2
    assert repository.get(schedule["id"])["next_date"] == "2026-05-01"


def test_failure_rolls_back_claims_transactions_and_schedule(db):
    schedule = add_schedule(db)
    conn = db.database.conn
    conn.execute("""CREATE TRIGGER fail_occurrence BEFORE INSERT ON transactions
        WHEN NEW.date = '2026-03-01' BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        db.recurring_transactions.process_due(date(2026, 4, 1))
    assert db.list_transactions()[1] == 0
    assert conn.execute("SELECT COUNT(*) FROM recurring_occurrences").fetchone()[0] == 0
    assert db.recurring_transactions.get(schedule["id"])["next_date"] == "2026-02-01"
    conn.execute("DROP TRIGGER fail_occurrence")
    assert db.recurring_transactions.process_due(date(2026, 4, 1)) == 3


def test_concurrent_workers_create_one_occurrence_each(db):
    add_schedule(db)
    barrier = Barrier(4)

    def process():
        with db.database.connection() as connection:
            repository = RecurringRepository(connection)
            barrier.wait(timeout=5)
            return repository.process_due(date(2026, 4, 1))

    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [workers.submit(process) for _ in range(4)]
        assert sum(future.result(timeout=10) for future in futures) == 3
    assert db.list_transactions()[1] == 3
    assert db.database.conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0] == 3075


def test_inactive_schedule_is_not_processed(db):
    schedule = add_schedule(db)
    db.delete_recurring(schedule["id"])
    assert db.recurring_transactions.process_due(date(2026, 4, 1)) == 0


def test_processing_rejects_an_existing_transaction(db):
    db.database.conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RuntimeError, match="own transaction"):
            db.recurring_transactions.process_due()
    finally:
        db.database.conn.rollback()


def test_version_two_upgrade_preserves_existing_schedule_and_money(db):
    schedule = add_schedule(db)
    conn = db.database.conn
    db.recurring_transactions.process_due(date(2026, 2, 1))
    before = db.list_transactions()
    with conn:
        conn.execute("DROP TABLE recurring_occurrences")
        conn.execute("DELETE FROM schema_migrations WHERE version=3")
    assert migrate(conn) == 3
    assert db.list_transactions() == before
    assert db.recurring_transactions.get(schedule["id"])["next_date"] == "2026-03-01"
    assert db.recurring_transactions.process_due(date(2026, 3, 1)) == 1
    assert conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0] == 2050
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_command_retries_without_duplicates(db, capsys):
    add_schedule(db)
    args = ["process-recurring", "--database", db.database.db_path]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["created"] > 0
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["created"] == 0


def test_runner_retries_errors_and_stops_cleanly(db, monkeypatch):
    calls = []

    def process(database):
        calls.append(database)
        if len(calls) == 1:
            raise sqlite3.OperationalError("locked")
        return 0

    monkeypatch.setattr(recurring_runner, "process_recurring", process)

    async def exercise():
        stop = asyncio.Event()
        task = asyncio.create_task(recurring_runner.run_recurring(db.database, stop, interval=0.01))
        try:
            async with asyncio.timeout(5):
                while len(calls) < 2:
                    await asyncio.sleep(0.01)
        finally:
            stop.set()
            await task

    asyncio.run(exercise())
    assert len(calls) >= 2
