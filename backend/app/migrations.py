"""Small, explicit SQLite schema migration runner.

Migrations are intentionally kept in Python so the application can upgrade an
existing desktop-era database without requiring a separate migration command.
"""

import sqlite3
from datetime import datetime, timezone

LATEST_SCHEMA_VERSION = 1


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _migration_1_accounts_and_transfers(conn: sqlite3.Connection) -> None:
    """Add accounts/transfers while preserving every legacy transaction."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL DEFAULT 'checking',
            currency TEXT NOT NULL DEFAULT 'USD',
            opening_balance REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            from_account_id INTEGER NOT NULL,
            to_account_id INTEGER NOT NULL,
            amount REAL NOT NULL CHECK (amount > 0),
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (from_account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
            FOREIGN KEY (to_account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
            CHECK (from_account_id <> to_account_id)
        );
        """
    )

    if not _column_exists(conn, "transactions", "account_id"):
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL"
        )

    if not _column_exists(conn, "recurring_transactions", "account_id"):
        conn.execute(
            "ALTER TABLE recurring_transactions ADD COLUMN account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL"
        )

    default_account = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Main Account' LIMIT 1"
    ).fetchone()
    if default_account is None:
        cur = conn.execute(
            """
            INSERT INTO accounts(name, type, currency, opening_balance, active, created_at)
            VALUES ('Main Account', 'checking', 'USD', 0, 1, ?)
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        default_account_id = cur.lastrowid
    else:
        default_account_id = default_account[0]

    # Legacy records had no account. Put them in Main Account so the total
    # balance remains exactly the same after the migration.
    conn.execute(
        "UPDATE transactions SET account_id = ? WHERE account_id IS NULL",
        (default_account_id,),
    )
    conn.execute(
        "UPDATE recurring_transactions SET account_id = ? WHERE account_id IS NULL",
        (default_account_id,),
    )

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_transactions_account_date
            ON transactions(account_id, date);
        CREATE INDEX IF NOT EXISTS idx_transfers_date
            ON transfers(date);
        CREATE INDEX IF NOT EXISTS idx_transfers_from_account
            ON transfers(from_account_id);
        CREATE INDEX IF NOT EXISTS idx_transfers_to_account
            ON transfers(to_account_id);
        CREATE INDEX IF NOT EXISTS idx_recurring_account
            ON recurring_transactions(account_id);
        """
    )


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all migrations and return the resulting schema version."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )

    current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]

    migrations = {1: _migration_1_accounts_and_transfers}
    for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
        migration = migrations[version]
        with conn:
            migration(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )

    return LATEST_SCHEMA_VERSION
