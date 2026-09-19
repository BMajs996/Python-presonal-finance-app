import asyncio
import logging

from ..database import FinanceDatabase
from ..repositories.recurring_repository import RecurringRepository

logger = logging.getLogger(__name__)


def process_recurring(database: FinanceDatabase) -> int:
    with database.connection() as connection:
        return RecurringRepository(connection, database.base_currency).process_due()


async def run_recurring(database: FinanceDatabase, stop: asyncio.Event, interval: float = 60) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(process_recurring, database)
        except Exception:
            # Retry on the next tick without logging financial payloads.
            logger.error("Recurring processing failed; retrying on the next interval")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
