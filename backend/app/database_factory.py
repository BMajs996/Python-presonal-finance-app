from .database import FinanceDatabase
from .postgres_database import PostgresDatabase


def open_database(settings):
    if settings.database_url:
        return PostgresDatabase(settings.database_url.get_secret_value(), settings.base_currency)
    return FinanceDatabase(settings.database_path, settings.base_currency)
