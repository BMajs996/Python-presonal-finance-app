import asyncio
import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta
from threading import Event

import psycopg
import pytest
from app.services import recurring_runner
from app.services.worker_health import WorkerHealth, error_code


class Clock:
    seconds = 0.0

    def now(self):
        return datetime(2026, 10, 12, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds


def test_initial_state_stale_backoff_and_recovery(caplog):
    clock = Clock()
    health = WorkerHealth(clock=clock.now, monotonic=clock.monotonic, stale_seconds=10)
    assert health.snapshot()["status"] == "starting"
    clock.seconds = 11
    assert health.snapshot()["reasons"] == ["heartbeat_stale"]
    with caplog.at_level(logging.INFO):
        health.observe()
        health.observe()
        assert len(caplog.records) == 1
        health.begin()
        health.finish(created=0, today=date(2026, 10, 12), delay=300)
        health.observe()
        assert caplog.records[-1].message == "Recurring health recovered"
        clock.seconds = 300
        assert health.snapshot()["status"] == "ok"
        clock.seconds = 322
        assert health.snapshot()["reasons"] == ["heartbeat_stale"]
    assert health.snapshot()["last_success_at"].tzinfo == UTC


def test_stalled_processing_and_lag_are_separate():
    clock = Clock()
    health = WorkerHealth(clock=clock.now, monotonic=clock.monotonic, stale_seconds=10)
    health.begin()
    clock.seconds = 11
    assert health.snapshot()["reasons"] == ["processing_stalled"]
    health.finish(created=100, oldest=date(2026, 10, 9), today=date(2026, 10, 12), delay=60)
    snapshot = health.snapshot()
    assert snapshot["reasons"] == ["backlog_lag"]
    assert snapshot["lag_days"] == 3
    assert snapshot["last_created"] == 100
    assert snapshot["last_duration_seconds"] == 11
    health.stopped()
    assert health.snapshot()["status"] == "stopped"


@pytest.mark.parametrize(
    "error,expected",
    [
        (sqlite3.OperationalError("sensitive"), "database_unavailable"),
        (sqlite3.IntegrityError("sensitive"), "invalid_data"),
        (psycopg.OperationalError("postgres://password"), "database_unavailable"),
        (psycopg.errors.QueryCanceled("sensitive"), "database_timeout"),
        (psycopg.errors.LockNotAvailable("sensitive"), "database_busy"),
        (ValueError("sensitive"), "invalid_data"),
        (RuntimeError("sensitive"), "unexpected_error"),
    ],
)
def test_error_classification_does_not_use_messages(error, expected):
    assert error_code(error) == expected


def test_backoff_is_bounded_and_recovery_resets_failures(monkeypatch, caplog):
    calls, waits = [], []
    health = WorkerHealth()
    real_wait = asyncio.wait_for

    async def exercise():
        stop = asyncio.Event()

        def process(_database, _should_stop=None):
            calls.append(1)
            if len(calls) <= 4:
                raise sqlite3.OperationalError("secret-description amount=123 password=DO-NOT-LOG")
            stop.set()
            return 0, None, date(2026, 10, 12)

        async def wait(awaitable, timeout):
            waits.append(timeout)
            return await real_wait(awaitable, timeout=timeout)

        monkeypatch.setattr(recurring_runner, "process_pass", process)
        monkeypatch.setattr(recurring_runner.asyncio, "wait_for", wait)
        await recurring_runner._process_loop(None, stop, 0.001, 0.003, health)

    with caplog.at_level(logging.INFO):
        asyncio.run(exercise())
        health.observe()
    assert waits == [0.001, 0.002, 0.003, 0.003, 0.001]
    snapshot = health.snapshot()
    assert snapshot["consecutive_failures"] == 0
    assert snapshot["last_created"] == 0
    assert snapshot["last_failure_at"] is not None
    assert sum("health alert" in record.message for record in caplog.records) == 1
    assert "health recovered" in caplog.text
    for secret in ("secret-description", "amount=123", "DO-NOT-LOG"):
        assert secret not in caplog.text


def test_failure_does_not_claim_zero_created_and_backlog_is_unknown():
    health = WorkerHealth()
    health.begin()
    health.finish(created=3, oldest=date(2026, 10, 10), today=date(2026, 10, 12), delay=60)
    health.begin()
    health.finish(failure="database_unavailable", delay=60)
    snapshot = health.snapshot()
    assert snapshot["last_created"] is None
    assert snapshot["lag_days"] is None
    assert snapshot["oldest_due_date"] is None
    assert snapshot["last_success_at"] is not None
    assert snapshot["status"] == "degraded"


def test_stop_interrupts_backoff_without_another_attempt(monkeypatch):
    calls = []

    async def exercise():
        stop = asyncio.Event()

        def process(_database, _should_stop=None):
            calls.append(1)
            stop.set()
            raise ValueError("bad schedule")

        monkeypatch.setattr(recurring_runner, "process_pass", process)
        health = WorkerHealth()
        async with asyncio.timeout(1):
            await recurring_runner.run_recurring(None, stop, interval=60, health=health)
        assert health.snapshot()["status"] == "stopped"

    asyncio.run(exercise())
    assert len(calls) == 1


def test_unexpected_task_exit_marks_worker_unavailable(monkeypatch, caplog):
    async def broken(*args):
        raise RuntimeError("internal failure")

    monkeypatch.setattr(recurring_runner, "_process_loop", broken)
    health = WorkerHealth()
    with pytest.raises(ExceptionGroup):
        asyncio.run(recurring_runner.run_recurring(None, asyncio.Event(), health=health))
    assert health.snapshot()["status"] == "stopped"
    assert "worker_stopped" in caplog.text
    assert "internal failure" not in caplog.text


def test_observer_detects_stall_while_processing_is_blocked(monkeypatch, caplog):
    entered, release = Event(), Event()
    now = [0.0]
    calls = []
    health = WorkerHealth(monotonic=lambda: now[0], stale_seconds=10)

    def process(_database, _should_stop):
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return 0, None, date(2026, 10, 12)

    monkeypatch.setattr(recurring_runner, "process_pass", process)

    async def exercise():
        stop = asyncio.Event()
        task = asyncio.create_task(recurring_runner.run_recurring(None, stop, interval=0.01, health=health))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            now[0] = 11
            async with asyncio.timeout(1):
                while "processing_stalled" not in caplog.text:
                    await asyncio.sleep(0.01)
            assert len(calls) == 1
        finally:
            stop.set()
            release.set()
            await task

    asyncio.run(exercise())
