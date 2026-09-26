from ..domain.errors import NotFound
from .account_repository import AccountRepository
from .base_repository import BaseRepository


class ReconciliationRepository(BaseRepository):
    def accounts(self):
        return AccountRepository(self.conn, self.base_currency).list(include_inactive=True)

    def get(self, ident: int):
        row = self.conn.execute(
            """SELECT r.*, a.name AS account_name, a.currency FROM reconciliations r
            JOIN accounts a ON a.id=r.account_id WHERE r.id=?""",
            (ident,),
        ).fetchone()
        if row is None:
            raise NotFound("Statement not found")
        return dict(row)

    def list(self, account_id: int):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM reconciliations WHERE account_id=? ORDER BY closing_date DESC, id DESC",
                (account_id,),
            )
        ]

    def entries(self, statement):
        return [
            dict(row)
            for row in self.conn.execute(
                """
            SELECT l.*, (e.reconciliation_id IS NOT NULL) AS cleared
            FROM reconciliation_ledger l
            LEFT JOIN reconciliation_entries e ON e.account_id=l.account_id
                AND ((l.kind='transaction' AND l.entry_id=e.transaction_id)
                  OR (l.kind='transfer' AND l.entry_id=e.transfer_id))
            WHERE l.account_id=? AND l.date<=?
              AND (e.reconciliation_id=? OR (e.id IS NULL AND ?='draft'))
            ORDER BY l.date, l.kind, l.entry_id
            """,
                (statement["account_id"], statement["closing_date"], statement["id"], statement["status"]),
            )
        ]

    def create(self, account_id: int, closing_date: str, opening: int, closing: int):
        cursor = self.conn.execute(
            """INSERT INTO reconciliations(account_id, closing_date, opening_balance_cents,
            closing_balance_cents) VALUES (?, ?, ?, ?)""",
            (account_id, closing_date, opening, closing),
        )
        return self.inserted_id(cursor)

    def clear(self, statement, kind: str, entry_id: int, cleared: bool):
        transaction_id = entry_id if kind == "transaction" else None
        transfer_id = entry_id if kind == "transfer" else None
        if cleared:
            self.conn.execute(
                """INSERT INTO reconciliation_entries(
                    reconciliation_id, account_id, transaction_id, transfer_id)
                VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (statement["id"], statement["account_id"], transaction_id, transfer_id),
            )
        else:
            self.conn.execute(
                """DELETE FROM reconciliation_entries WHERE reconciliation_id=?
                AND transaction_id IS ? AND transfer_id IS ?""",
                (statement["id"], transaction_id, transfer_id),
            )

    def complete(self, ident: int):
        self.conn.execute(
            """UPDATE reconciliations SET status='completed',
            completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
            (ident,),
        )

    def cancel(self, ident: int):
        self.conn.execute("DELETE FROM reconciliation_entries WHERE reconciliation_id=?", (ident,))
        self.conn.execute("DELETE FROM reconciliations WHERE id=?", (ident,))
