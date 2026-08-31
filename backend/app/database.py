import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .migrations import migrate


class FinanceDatabase:
    """Configure SQLite connections and keep the schema current."""

    def __init__(
        self,
        db_path: str | Path,
        base_currency: str = "USD",
        busy_timeout_ms: int = 5_000,
    ):
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms cannot be negative")
        self.db_path = str(db_path)
        self.base_currency = base_currency
        self.busy_timeout_ms = busy_timeout_ms
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = self.connect()
        try:
            self._initialize_schema()
        except BaseException:
            self.conn.close()
            raise

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            timeout=self.busy_timeout_ms / 1_000,
            check_same_thread=False,
            isolation_level="IMMEDIATE",
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    def _initialize_schema(self):
        # Create legacy tables first so migrations work for fresh and existing databases.
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                type TEXT,
                category TEXT,
                amount REAL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS recurring_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                category TEXT,
                amount REAL,
                description TEXT,
                frequency TEXT,
                next_date TEXT,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT UNIQUE,
                monthly_limit REAL,
                month_year TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        migrate(self.conn, self.base_currency)
        self.conn.commit()

    def close(self):
        self.conn.close()
