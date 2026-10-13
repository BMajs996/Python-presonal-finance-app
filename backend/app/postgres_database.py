from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool, PoolTimeout, TooManyRequests

from .database_errors import DatabaseCapacityError
from .migrations_ownership import migrate_ownership
from .migrations_query_indexes import migrate_query_indexes
from .migrations_user_accounts import migrate_user_accounts
from .postgres_connection import WRITE_LOCK, PostgresConnection, record_factory

TABLES = (
    "users",
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
SCHEMA_VERSION = 4


def create_schema(connection):
    connection.execute((Path(__file__).with_name("postgres_schema.sql")).read_text())
    connection.execute("CREATE TABLE postgres_schema_migrations (version INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO postgres_schema_migrations VALUES (1)")
    migrate_schema(connection)


def migrate_schema(connection):
    versions = [
        row[0]
        for row in connection.execute(
            "SELECT version FROM postgres_schema_migrations ORDER BY version"
        ).fetchall()
    ]
    if not versions or versions[-1] > SCHEMA_VERSION or versions != list(range(1, versions[-1] + 1)):
        raise ValueError("Unsupported PostgreSQL schema version")
    migrations = {2: migrate_query_indexes, 3: migrate_ownership, 4: migrate_user_accounts}
    for version in range(versions[-1] + 1, SCHEMA_VERSION + 1):
        migrations[version](connection)
        connection.execute("INSERT INTO postgres_schema_migrations VALUES (%s)", (version,))


def install_guards(connection):
    connection.execute((Path(__file__).with_name("postgres_guards.sql")).read_text())
    for table in TABLES:
        if table == "users":
            continue
        connection.execute(
            sql.SQL(
                "CREATE TRIGGER finance_writer_lock BEFORE INSERT OR UPDATE OR DELETE ON {} "
                "FOR EACH STATEMENT EXECUTE FUNCTION finance_writer_lock()"
            ).format(sql.Identifier(table))
        )


class PostgresDatabase:
    def __init__(
        self,
        url: str,
        base_currency: str = "USD",
        *,
        pool_size: int = 5,
        pool_timeout: float = 2,
        pool_max_waiting: int = 20,
    ):
        if not (1 <= pool_size <= 20 and 0.1 <= pool_timeout <= 10 and 1 <= pool_max_waiting <= 100):
            raise ValueError("Database pool capacity settings are out of bounds")
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
                    migrate_schema(self.conn.raw)
                main = self.conn.raw.execute(
                    "SELECT currency FROM accounts WHERE user_id=1 AND name='Main Account'"
                ).fetchone()
                if main is None or main[0] != base_currency:
                    raise ValueError("PostgreSQL Main Account currency does not match BASE_CURRENCY")
        except BaseException:
            self.close()
            raise
        self.pool = ConnectionPool(
            url,
            min_size=0,
            max_size=pool_size,
            timeout=pool_timeout,
            max_waiting=pool_max_waiting,
            num_workers=1,
            open=False,
            kwargs={
                "autocommit": True,
                "row_factory": record_factory,
                "connect_timeout": 3,
                "prepare_threshold": None,
            },
            configure=self._configure_connection,
            reset=self._reset_connection,
            check=ConnectionPool.check_connection,
        )

    @staticmethod
    def _configure_connection(raw):
        raw.execute("SET lock_timeout = '10s'; SET statement_timeout = '60s'")

    @classmethod
    def _reset_connection(cls, raw):
        raw.rollback()
        raw.autocommit = True
        # Drop temporary objects, session locks, roles and session-local settings.
        # Server-side prepare is disabled so DISCARD cannot invalidate a driver cache.
        raw.execute("DISCARD ALL")
        raw.row_factory = record_factory
        cls._configure_connection(raw)

    def connect(self) -> PostgresConnection:
        raw = psycopg.connect(self._url, autocommit=True, row_factory=record_factory, connect_timeout=10)
        raw.execute("SET lock_timeout = '10s'")
        raw.execute("SET statement_timeout = '60s'")
        return PostgresConnection(raw)

    @contextmanager
    def connection(self):
        self.pool.open()
        try:
            raw = self.pool.getconn()
        except (PoolTimeout, TooManyRequests) as exc:
            raise DatabaseCapacityError("Database capacity temporarily unavailable") from exc
        connection = PostgresConnection(raw)
        try:
            yield connection
        finally:
            try:
                if not raw.closed:
                    raw.rollback()
            finally:
                self.pool.putconn(raw)

    @contextmanager
    def operational_transaction(self):
        with self.connection() as connection, connection.raw.transaction():
            # Auth metadata must not contend with the financial writer lock.
            connection.raw.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK + 1,))
            yield connection

    def close(self):
        self.conn.close()
        if hasattr(self, "pool"):
            self.pool.close()

    def check_ready(self) -> bool:
        from .services.health_service import SCHEMA_PROBE

        # Preserve URL options such as the isolated test-schema search_path.
        options = str(conninfo_to_dict(self._url).get("options") or "")
        options += " -c statement_timeout=2000 -c lock_timeout=2000 -c default_transaction_read_only=on"
        with psycopg.connect(self._url, connect_timeout=2, options=options, autocommit=True) as connection:
            row = connection.execute(
                SCHEMA_PROBE.format(migration_table="postgres_schema_migrations")
            ).fetchone()
            return row is not None and row[0] == self.base_currency and row[1] == SCHEMA_VERSION
