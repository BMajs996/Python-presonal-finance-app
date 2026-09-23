"""Small, explicit SQLite schema migration runner.

Migrations are intentionally kept in Python so the application can upgrade an
existing desktop-era database without requiring a separate migration command.
"""

import sqlite3
from datetime import UTC, datetime

LATEST_SCHEMA_VERSION = 4

MONEY_COLUMNS = (
    ("transactions", "amount", "amount_cents"),
    ("recurring_transactions", "amount", "amount_cents"),
    ("budgets", "monthly_limit", "monthly_limit_cents"),
    ("accounts", "opening_balance", "opening_balance_cents"),
    ("transfers", "amount", "amount_cents"),
)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _migration_1_accounts_and_transfers(
    conn: sqlite3.Connection,
    base_currency: str,
) -> None:
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
            "ALTER TABLE transactions ADD COLUMN account_id INTEGER "
            "REFERENCES accounts(id) ON DELETE SET NULL"
        )

    if not _column_exists(conn, "recurring_transactions", "account_id"):
        conn.execute(
            "ALTER TABLE recurring_transactions ADD COLUMN account_id INTEGER "
            "REFERENCES accounts(id) ON DELETE SET NULL"
        )

    default_account = conn.execute("SELECT id FROM accounts WHERE name = 'Main Account' LIMIT 1").fetchone()
    if default_account is None:
        cur = conn.execute(
            """
            INSERT INTO accounts(name, type, currency, opening_balance, active, created_at)
            VALUES ('Main Account', 'checking', ?, 0, 1, ?)
            """,
            (base_currency, datetime.now(UTC).isoformat()),
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


def _migration_2_integer_money(
    conn: sqlite3.Connection,
    _base_currency: str,
) -> None:
    """Add exact integer-cent columns while retaining legacy REAL columns."""
    money_columns = (
        ("transactions", "amount", "amount_cents"),
        ("recurring_transactions", "amount", "amount_cents"),
        ("budgets", "monthly_limit", "monthly_limit_cents"),
        ("accounts", "opening_balance", "opening_balance_cents"),
        ("transfers", "amount", "amount_cents"),
    )
    for table, legacy_column, cents_column in money_columns:
        if not _column_exists(conn, table, cents_column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {cents_column} INTEGER")
        # Identifiers come only from the fixed money_columns tuple above.
        backfill_sql = f"""
            UPDATE {table}
            SET {cents_column}=CAST(ROUND(COALESCE({legacy_column}, 0) * 100) AS INTEGER)
            WHERE {cents_column} IS NULL
            """
        conn.execute(backfill_sql)


def _migration_3_recurring_occurrences(conn: sqlite3.Connection, _base_currency: str) -> None:
    conn.execute(
        """
        CREATE TABLE recurring_occurrences (
            recurring_id INTEGER NOT NULL REFERENCES recurring_transactions(id) ON DELETE RESTRICT,
            due_date TEXT NOT NULL,
            PRIMARY KEY (recurring_id, due_date)
        )
        """
    )


def _invalid_money(legacy: str, cents: str, allow_negative: bool) -> str:
    conditions = [
        f"typeof({cents}) <> 'integer'",
        f"typeof({legacy}) NOT IN ('integer', 'real')",
        f"{legacy} <> {cents} / 100.0",
    ]
    if not allow_negative:
        conditions.append(f"{cents} <= 0")
    return " OR ".join(conditions)


def _migration_4_money_constraints(conn: sqlite3.Connection, _base_currency: str) -> None:
    # Explicitly start a transaction before DDL so failed upgrades leave no partial guards.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    for table, legacy, cents in MONEY_COLUMNS:
        invalid = _invalid_money(legacy, cents, table == "accounts")
        # Identifiers and predicates come only from fixed schema definitions.
        row = conn.execute(f"SELECT id FROM {table} WHERE {invalid} LIMIT 1").fetchone()  # nosec B608
        if row is not None:
            raise ValueError(
                f"Money validation failed in {table}, row {row[0]}; "
                "restore a verified backup or repair the row before retrying the upgrade"
            )
        new_invalid = _invalid_money(f"NEW.{legacy}", f"NEW.{cents}", table == "accounts")
        for operation in ("INSERT", "UPDATE"):
            conn.execute(
                f"""
                CREATE TRIGGER money_{table}_{operation.lower()}
                BEFORE {operation} ON {table}
                WHEN {new_invalid}
                BEGIN
                    SELECT RAISE(ABORT, 'Invalid or inconsistent money values');
                END
                """
            )


def migrate(conn: sqlite3.Connection, base_currency: str = "USD") -> int:
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

    migrations = {
        1: _migration_1_accounts_and_transfers,
        2: _migration_2_integer_money,
        3: _migration_3_recurring_occurrences,
        4: _migration_4_money_constraints,
    }
    for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
        migration = migrations[version]
        with conn:
            migration(conn, base_currency)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )

    return LATEST_SCHEMA_VERSION
