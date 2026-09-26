"""Psycopg connection boundary for the repositories' fixed, parameterized SQL.

Only DB-API bind markers differ. Queries use portable SQL and must not put question
marks in SQL literals; all user text is passed separately as bound parameters.
"""

from typing import Any

import psycopg
from psycopg.pq import TransactionStatus

WRITE_LOCK = 618370201


class Record(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def record_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values, strict=True))


class PostgresConnection:
    def __init__(self, connection: psycopg.Connection):
        self.raw = connection
        self._depth = 0

    @property
    def in_transaction(self) -> bool:
        return self.raw.info.transaction_status != TransactionStatus.IDLE

    def begin_write(self):
        if not self.in_transaction:
            self.raw.execute("BEGIN")
            self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))

    def execute(self, query: str, parameters: Any = ()):
        if query.strip().upper() == "BEGIN IMMEDIATE":
            self.begin_write()
            return self.raw.cursor()
        if self._depth:
            self.begin_write()
        # Bind values are never interpolated into SQL.
        return self.raw.execute(query.replace("?", "%s"), parameters or None)

    def __enter__(self):
        self._depth += 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._depth -= 1
        if self._depth == 0:
            if exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        return False

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()
