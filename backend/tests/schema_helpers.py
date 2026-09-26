"""Helpers for reconstructing historical schemas in isolated test databases."""


def remove_reconciliation(conn):
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
