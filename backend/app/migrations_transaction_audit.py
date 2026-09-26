"""Migration 5: recoverable transactions and atomic, append-only history."""

import sqlite3


def migrate_transaction_audit(conn: sqlite3.Connection, _base_currency: str) -> None:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute("ALTER TABLE transactions ADD COLUMN deleted_at TEXT")
    conn.execute(
        """
        CREATE TABLE transaction_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE RESTRICT,
            action TEXT NOT NULL CHECK(action IN ('created', 'updated', 'deleted', 'restored')),
            occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            actor TEXT NOT NULL DEFAULT 'local',
            before_state TEXT CHECK(before_state IS NULL OR json_valid(before_state)),
            after_state TEXT NOT NULL CHECK(json_valid(after_state))
        )
        """
    )
    conn.execute("CREATE INDEX idx_transaction_audit_history ON transaction_audit(transaction_id, id)")
    conn.execute("CREATE INDEX idx_transactions_deleted ON transactions(deleted_at, date)")
    snapshots = {}
    fields = ("id", "date", "type", "category", "amount_cents", "description", "account_id", "deleted_at")
    for prefix in ("OLD", "NEW"):
        pairs = ", ".join(f"'{field}', {prefix}.{field}" for field in fields)
        snapshots[prefix] = (
            f"json_object({pairs}, "
            f"'currency', (SELECT currency FROM accounts WHERE id={prefix}.account_id), "
            f"'account_name', (SELECT name FROM accounts WHERE id={prefix}.account_id))"
        )
    # These SQL fragments contain only fixed field names and OLD/NEW prefixes, never user input.
    conn.execute(
        f"""
        CREATE TRIGGER transaction_audit_insert AFTER INSERT ON transactions
        BEGIN
            INSERT INTO transaction_audit(transaction_id, action, after_state)
            VALUES (NEW.id, 'created', {snapshots["NEW"]});
        END
        """  # nosec B608
    )
    changed = " OR ".join(f"OLD.{field} IS NOT NEW.{field}" for field in fields)
    conn.execute(
        f"""
        CREATE TRIGGER transaction_audit_update AFTER UPDATE ON transactions
        WHEN {changed}
        BEGIN
            INSERT INTO transaction_audit(transaction_id, action, before_state, after_state)
            VALUES (
                NEW.id,
                CASE
                    WHEN OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN 'deleted'
                    WHEN OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN 'restored'
                    ELSE 'updated'
                END,
                {snapshots["OLD"]}, {snapshots["NEW"]}
            );
        END
        """  # nosec B608
    )
    conn.execute(
        """
        CREATE TRIGGER transactions_no_hard_delete BEFORE DELETE ON transactions
        BEGIN SELECT RAISE(ABORT, 'Transactions must be soft deleted'); END
        """
    )
    for operation in ("UPDATE", "DELETE"):
        conn.execute(
            f"""
            CREATE TRIGGER transaction_audit_no_{operation.lower()} BEFORE {operation} ON transaction_audit
            BEGIN SELECT RAISE(ABORT, 'Transaction audit history is append-only'); END
            """
        )
