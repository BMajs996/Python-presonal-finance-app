from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

from .postgres_connection import WRITE_LOCK, PostgresConnection, record_factory

TABLES = (
    "accounts",
    "transactions",
    "recurring_transactions",
    "budgets",
    "transfers",
    "settings",
    "schema_migrations",
    "recurring_occurrences",
    "transaction_audit",
    "reconciliations",
    "reconciliation_entries",
)
SCHEMA_VERSION = 1


def create_schema(connection):
    connection.execute((Path(__file__).with_name("postgres_schema.sql")).read_text())
    connection.execute("CREATE TABLE postgres_schema_migrations (version INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO postgres_schema_migrations VALUES (%s)", (SCHEMA_VERSION,))


def install_guards(connection):
    connection.execute((Path(__file__).with_name("postgres_guards.sql")).read_text())
    for table in TABLES:
        connection.execute(
            sql.SQL(
                "CREATE TRIGGER finance_writer_lock BEFORE INSERT OR UPDATE OR DELETE ON {} "
                "FOR EACH STATEMENT EXECUTE FUNCTION finance_writer_lock()"
            ).format(sql.Identifier(table))
        )


class PostgresDatabase:
    def __init__(self, url: str, base_currency: str = "USD"):
        self._url = url
        self.base_currency = base_currency
        self.conn = self.connect()
        try:
            with self.conn.raw.transaction():
                self.conn.raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
                row = self.conn.raw.execute("SELECT to_regclass('postgres_schema_migrations')").fetchone()
                found = row[0] if row else None
                if found is None:
                    create_schema(self.conn.raw)
                    install_guards(self.conn.raw)
                    self.conn.raw.execute(
                        """INSERT INTO accounts(name,type,currency,opening_balance,opening_balance_cents,
                        active,created_at) VALUES ('Main Account','checking',%s,0,0,1,%s)""",
                        (base_currency, datetime.now(UTC).isoformat()),
                    )
                else:
                    version_row = self.conn.raw.execute(
                        "SELECT MAX(version) FROM postgres_schema_migrations"
                    ).fetchone()
                    if version_row is None or version_row[0] != SCHEMA_VERSION:
                        raise ValueError("Unsupported PostgreSQL schema version")
                main = self.conn.raw.execute(
                    "SELECT currency FROM accounts WHERE name='Main Account'"
                ).fetchone()
                if main is None or main[0] != base_currency:
                    raise ValueError("PostgreSQL Main Account currency does not match BASE_CURRENCY")
        except BaseException:
            self.close()
            raise

    def connect(self) -> PostgresConnection:
        raw = psycopg.connect(self._url, autocommit=True, row_factory=record_factory, connect_timeout=10)
        raw.execute("SET lock_timeout = '10s'")
        raw.execute("SET statement_timeout = '60s'")
        return PostgresConnection(raw)

    @contextmanager
    def connection(self):
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.rollback()
            connection.close()

    @contextmanager
    def operational_transaction(self):
        with self.connection() as connection, connection.raw.transaction():
            # Auth metadata must not contend with the financial writer lock.
            connection.raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK + 1,))
            yield connection

    def close(self):
        self.conn.close()
