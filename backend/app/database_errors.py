import sqlite3

import psycopg

INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


class DatabaseCapacityError(TimeoutError):
    """The bounded database pool cannot serve this operation now."""


def is_unique_violation(error) -> bool:
    return (
        isinstance(error, psycopg.errors.UniqueViolation)
        or getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
    )


def constraint_message(error) -> str:
    if isinstance(error, psycopg.Error):
        return error.diag.message_primary or "Database constraint violation"
    return str(error)
