import asyncio
import logging
from collections.abc import Callable
from datetime import date
from threading import Event

from ..database import FinanceDatabase
from ..domain import business_date
from ..postgres_database import PostgresDatabase
from ..repositories.recurring_repository import SCHEDULE_BATCH_SIZE, RecurringRepository
from .worker_health import WorkerHealth, error_code, safe_location

logger = logging.getLogger("uvicorn.error.recurring")


def process_recurring(
    database: FinanceDatabase | PostgresDatabase,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    with business_date.snapshot(), database.connection() as connection:
        rows = connection.execute(
            "SELECT r.id,a.user_id FROM recurring_transactions r JOIN accounts a ON a.id=r.account_id "
            "JOIN users u ON u.id=a.user_id WHERE r.active=1 AND u.active=1 AND r.next_date<=? "
            "ORDER BY r.next_date,r.id LIMIT ?",
            (business_date.today().isoformat(), SCHEDULE_BATCH_SIZE),
        ).fetchall()
        groups: dict[int, list[int]] = {}
        for row in rows:
            groups.setdefault(row["user_id"], []).append(row["id"])
        created = 0
        for user_id, ids in groups.items():
            if should_stop and should_stop():
                break
            created += RecurringRepository(connection, database.base_currency, user_id=user_id).process_due(
                should_stop=should_stop, schedule_ids=ids
            )
        return created


def process_pass(database, should_stop=None):
    with business_date.snapshot():
        today = business_date.today()
        created = process_recurring(database, should_stop=should_stop)
        with database.connection() as connection:
            row = connection.execute(
                "SELECT MIN(r.next_date) FROM recurring_transactions r JOIN accounts a ON a.id=r.account_id "
                "JOIN users u ON u.id=a.user_id WHERE r.active=1 AND u.active=1 AND r.next_date<=?",
                (today.isoformat(),),
            ).fetchone()
            oldest = date.fromisoformat(row[0]) if row and row[0] else None
        return created, oldest, today


async def _watch(health: WorkerHealth, stop: asyncio.Event, interval: float, thread_stop: Event):
    try:
        while not stop.is_set():
            health.observe()
            try:
                await asyncio.wait_for(stop.wait(), timeout=min(5, interval))
            except TimeoutError:
                pass
    finally:
        thread_stop.set()


async def _process_loop(database, stop, interval, max_backoff, health, thread_stop: Event | None = None):
    delay = interval
    while not stop.is_set():
        health.begin()
        try:
            created, oldest, today = await asyncio.to_thread(
                process_pass,
                database,
                thread_stop.is_set if thread_stop else None,
            )
        except Exception as error:
            failures = health.snapshot()["consecutive_failures"] + 1
            delay = min(max_backoff, interval * 2 ** min(failures - 1, 20))
            code = error_code(error)
            health.finish(delay=delay, failure=code)
            logger.warning(
                "Recurring attempt failed code=%s location=%s retry_seconds=%s",
                code,
                safe_location(error),
                delay,
            )
        else:
            delay = interval
            health.finish(delay=delay, created=created, oldest=oldest, today=today)
        if not stop.is_set():
            health.observe()
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass


async def run_recurring(
    database: FinanceDatabase | PostgresDatabase,
    stop: asyncio.Event,
    interval: float = 60,
    *,
    max_backoff: float = 300,
    health: WorkerHealth | None = None,
) -> None:
    health = health or WorkerHealth()
    thread_stop = Event()
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(_watch(health, stop, interval, thread_stop))
            await _process_loop(database, stop, interval, max_backoff, health, thread_stop)
    finally:
        health.stopped()
        if not stop.is_set():
            health.observe()
