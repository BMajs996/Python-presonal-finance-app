import asyncio
import logging
from collections.abc import Callable
from threading import Event

from ..database import FinanceDatabase
from ..domain import business_date
from ..postgres_database import PostgresDatabase
from ..repositories.recurring_repository import RecurringRepository
from .worker_health import WorkerHealth, error_code, safe_location

logger = logging.getLogger("uvicorn.error.recurring")


def process_recurring(
    database: FinanceDatabase | PostgresDatabase,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    with business_date.snapshot(), database.connection() as connection:
        return RecurringRepository(connection, database.base_currency).process_due(should_stop=should_stop)


def process_pass(database, should_stop=None):
    with business_date.snapshot():
        today = business_date.today()
        created = process_recurring(database, should_stop=should_stop)
        with database.connection() as connection:
            oldest = RecurringRepository(connection, database.base_currency).oldest_due(today)
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
