from .database import FinanceDatabase
from .postgres_database import PostgresDatabase


def open_database(settings):
    if settings.database_url:
        return PostgresDatabase(
            settings.database_url.get_secret_value(),
            settings.base_currency,
            pool_size=settings.database_pool_size,
            pool_timeout=settings.database_pool_timeout,
            pool_max_waiting=settings.database_pool_max_waiting,
        )
    return FinanceDatabase(settings.database_path, settings.base_currency)
