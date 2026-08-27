import sqlite3
from pathlib import Path

from .migrations import migrate


class FinanceDatabase:
    """Own the SQLite connection and keep its schema current."""

    def __init__(self, db_path: str | Path, base_currency: str = "USD"):
        self.db_path = str(db_path)
        self.base_currency = base_currency
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self._initialize_schema()

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
