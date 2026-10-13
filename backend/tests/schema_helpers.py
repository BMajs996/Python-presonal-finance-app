"""Helpers for reconstructing historical schemas in isolated test databases."""


def remove_ownership(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
        return
    assert not conn.in_transaction
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    try:
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'ownership_%'"
        ).fetchall():
            conn.execute(f"DROP TRIGGER {row[0]}")
        for table, definition in (
            (
                "accounts",
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
                "type TEXT NOT NULL DEFAULT 'checking', currency TEXT NOT NULL DEFAULT 'USD', "
                "opening_balance REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, "
                "created_at TEXT NOT NULL, opening_balance_cents INTEGER",
            ),
            (
                "budgets",
                "id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT UNIQUE, "
                "monthly_limit REAL, month_year TEXT, monthly_limit_cents INTEGER",
            ),
        ):
            objects = [
                row[0]
                for row in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') "
                    "AND sql IS NOT NULL AND name<>'idx_accounts_owner'",
                    (table,),
                )
            ]
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})") if row[1] != "user_id"]
            conn.execute(f"CREATE TABLE {table}_legacy({definition})")
            names = ",".join(columns)
            conn.execute(f"INSERT INTO {table}_legacy({names}) SELECT {names} FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}_legacy RENAME TO {table}")
            for statement in objects:
                conn.execute(statement)
        conn.execute("DROP TABLE users")
        conn.execute("DELETE FROM schema_migrations WHERE version>=8")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table=OFF")
        conn.execute("PRAGMA foreign_keys=ON")


def remove_reconciliation(conn):
    remove_ownership(conn)
    from app.migrations_query_indexes import INDEXES

    for name in INDEXES:
        conn.execute("DROP INDEX " + name)
    conn.execute("DELETE FROM schema_migrations WHERE version=7")
    for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'reconciliation_%'"
    ).fetchall():
        conn.execute(f"DROP TRIGGER {row[0]}")
    conn.execute("DROP VIEW reconciliation_ledger")
    conn.execute("DROP TABLE reconciliation_entries")
    conn.execute("DROP TABLE reconciliations")
    conn.execute("DELETE FROM schema_migrations WHERE version=6")


def remove_transaction_audit(conn):
    remove_reconciliation(conn)
    for name in (
        "transaction_audit_insert",
        "transaction_audit_update",
        "transactions_no_hard_delete",
        "transaction_audit_no_update",
        "transaction_audit_no_delete",
    ):
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("DROP TABLE transaction_audit")
    conn.execute("DROP INDEX idx_transactions_deleted")
    conn.execute("ALTER TABLE transactions DROP COLUMN deleted_at")
    conn.execute("DELETE FROM schema_migrations WHERE version=5")
