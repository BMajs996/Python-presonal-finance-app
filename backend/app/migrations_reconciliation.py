"""Migration 6: account-specific statement reconciliation and retained evidence."""

import sqlite3


def migrate_reconciliation(conn: sqlite3.Connection, _currency: str) -> None:
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    statements = [
        """
        CREATE TABLE reconciliations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
            closing_date TEXT NOT NULL,
            opening_balance_cents INTEGER NOT NULL CHECK(typeof(opening_balance_cents)='integer'),
            closing_balance_cents INTEGER NOT NULL CHECK(typeof(closing_balance_cents)='integer'),
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','completed')),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            completed_at TEXT,
            UNIQUE(id, account_id),
            UNIQUE(account_id, closing_date)
        )
        """,
        "CREATE UNIQUE INDEX idx_reconciliation_draft ON reconciliations(account_id) WHERE status='draft'",
        """
        CREATE TABLE reconciliation_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reconciliation_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            transaction_id INTEGER REFERENCES transactions(id) ON DELETE RESTRICT,
            transfer_id INTEGER REFERENCES transfers(id) ON DELETE RESTRICT,
            CHECK((transaction_id IS NULL) <> (transfer_id IS NULL)),
            FOREIGN KEY(reconciliation_id, account_id) REFERENCES reconciliations(id, account_id),
            UNIQUE(account_id, transaction_id),
            UNIQUE(account_id, transfer_id)
        )
        """,
        "CREATE INDEX idx_reconciliation_entries ON reconciliation_entries(reconciliation_id)",
        """
        CREATE VIEW reconciliation_ledger AS
        SELECT account_id, id AS entry_id, 'transaction' AS kind, date,
               COALESCE(description, '') AS description, category AS label,
               CASE WHEN type='income' THEN amount_cents ELSE -amount_cents END AS amount_cents
        FROM transactions WHERE deleted_at IS NULL
        UNION ALL
        SELECT t.from_account_id, t.id, 'transfer', t.date, t.description,
               'Transfer to ' || a.name, -t.amount_cents
        FROM transfers t JOIN accounts a ON a.id=t.to_account_id
        UNION ALL
        SELECT t.to_account_id, t.id, 'transfer', t.date, t.description,
               'Transfer from ' || a.name, t.amount_cents
        FROM transfers t JOIN accounts a ON a.id=t.from_account_id
        """,
        """
        CREATE TRIGGER reconciliation_new BEFORE INSERT ON reconciliations
        WHEN NEW.status<>'draft' OR NEW.completed_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: statements must begin as drafts'); END
        """,
        """
        CREATE TRIGGER reconciliation_entry_insert BEFORE INSERT ON reconciliation_entries
        WHEN NOT EXISTS (
            SELECT 1 FROM reconciliations r JOIN reconciliation_ledger l ON l.account_id=r.account_id
            WHERE r.id=NEW.reconciliation_id AND r.account_id=NEW.account_id AND r.status='draft'
              AND l.date<=r.closing_date
              AND ((l.kind='transaction' AND l.entry_id=NEW.transaction_id)
                OR (l.kind='transfer' AND l.entry_id=NEW.transfer_id))
        )
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: entry is not eligible'); END
        """,
        """
        CREATE TRIGGER reconciliation_entry_update BEFORE UPDATE ON reconciliation_entries
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: cleared entries cannot be reassigned'); END
        """,
        """
        CREATE TRIGGER reconciliation_entry_delete BEFORE DELETE ON reconciliation_entries
        WHEN EXISTS (SELECT 1 FROM reconciliations WHERE id=OLD.reconciliation_id AND status='completed')
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: completed statements are read-only'); END
        """,
        """
        CREATE TRIGGER reconciliation_complete BEFORE UPDATE OF status ON reconciliations
        WHEN NEW.status='completed' AND (
            NEW.completed_at IS NULL OR NEW.closing_balance_cents <> NEW.opening_balance_cents +
            COALESCE((
                SELECT SUM(l.amount_cents) FROM reconciliation_entries e
                JOIN reconciliation_ledger l ON l.account_id=e.account_id
                  AND ((l.kind='transaction' AND l.entry_id=e.transaction_id)
                    OR (l.kind='transfer' AND l.entry_id=e.transfer_id))
                WHERE e.reconciliation_id=OLD.id
            ), 0)
        )
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: statement difference must be zero'); END
        """,
        """
        CREATE TRIGGER reconciliation_metadata BEFORE UPDATE OF
            account_id, closing_date, opening_balance_cents, closing_balance_cents ON reconciliations
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: cancel the draft to change statement details'); END
        """,
        """
        CREATE TRIGGER reconciliation_account BEFORE UPDATE OF opening_balance, opening_balance_cents,
            currency ON accounts
        WHEN EXISTS (SELECT 1 FROM reconciliations WHERE account_id=OLD.id)
          AND (NEW.opening_balance_cents IS NOT OLD.opening_balance_cents
            OR NEW.opening_balance IS NOT OLD.opening_balance OR NEW.currency IS NOT OLD.currency)
        BEGIN SELECT RAISE(ABORT, 'Reconciliation: account opening balance and currency are locked'); END
        """,
    ]
    for statement in statements:
        conn.execute(statement)
    # Identifiers below are a fixed schema mapping, never request input.
    for table, column in (("transactions", "transaction_id"), ("transfers", "transfer_id")):
        for operation in ("UPDATE", "DELETE"):
            conn.execute(
                f"""
                CREATE TRIGGER reconciliation_lock_{table}_{operation.lower()} BEFORE {operation} ON {table}
                WHEN EXISTS (SELECT 1 FROM reconciliation_entries WHERE {column}=OLD.id)
                BEGIN SELECT RAISE(ABORT,
                    'Reconciliation: entry locked; uncheck it in its draft before editing');
                END
                """  # nosec B608
            )
    for operation in ("UPDATE", "DELETE"):
        conn.execute(
            f"""
            CREATE TRIGGER reconciliation_final_{operation.lower()} BEFORE {operation} ON reconciliations
            WHEN OLD.status='completed'
            BEGIN SELECT RAISE(ABORT, 'Reconciliation: completed statements are read-only'); END
            """
        )
