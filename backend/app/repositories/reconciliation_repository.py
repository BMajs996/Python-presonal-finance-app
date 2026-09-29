from datetime import UTC, datetime

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
                """SELECT r.*, a.currency FROM reconciliations r
                JOIN accounts a ON a.id=r.account_id
                WHERE r.account_id=? ORDER BY r.closing_date DESC, r.id DESC""",
                (account_id,),
            )
        ]

    @staticmethod
    def _parameters(statement):
        return (statement["account_id"], statement["closing_date"], statement["id"], statement["status"])

    ELIGIBLE = """
        FROM reconciliation_ledger l
        LEFT JOIN reconciliation_entries e ON e.account_id=l.account_id
            AND ((l.kind='transaction' AND l.entry_id=e.transaction_id)
              OR (l.kind='transfer' AND l.entry_id=e.transfer_id))
        WHERE l.account_id=? AND l.date<=?
          AND (e.reconciliation_id=? OR (e.id IS NULL AND ?='draft'))
    """

    def entries(self, statement, limit=100, cursor=None):
        predicate = " AND (l.date,l.kind,l.entry_id)>(?,?,?)" if cursor else ""
        params = self._parameters(statement)
        if cursor:
            params += (cursor.date.isoformat(), cursor.kind, cursor.entry_id)
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT l.*, (e.reconciliation_id IS NOT NULL) AS cleared "
                + self.ELIGIBLE
                + predicate
                + " ORDER BY l.date,l.kind,l.entry_id LIMIT ?",
                (*params, limit),
            )
        ]

    def totals(self, statement):
        row = self.conn.execute(
            """SELECT COUNT(*) AS total_entries,
            COALESCE(SUM(CASE WHEN e.id IS NOT NULL THEN 1 ELSE 0 END),0) AS cleared_count,
            COALESCE(SUM(CASE WHEN e.id IS NOT NULL THEN l.amount_cents ELSE 0 END),0) AS cleared_cents """
            + self.ELIGIBLE,
            self._parameters(statement),
        ).fetchone()
        return {key: int(row[key]) for key in ("total_entries", "cleared_count", "cleared_cents")}

    def eligible(self, statement, kind, entry_id):
        return (
            self.conn.execute(
                "SELECT 1 " + self.ELIGIBLE + " AND l.kind=? AND l.entry_id=? LIMIT 1",
                (*self._parameters(statement), kind, entry_id),
            ).fetchone()
            is not None
        )

    def latest(self, account_id):
        return self.conn.execute(
            "SELECT * FROM reconciliations WHERE account_id=? ORDER BY closing_date DESC,id DESC LIMIT 1",
            (account_id,),
        ).fetchone()

    def has_draft(self, account_id):
        return (
            self.conn.execute(
                "SELECT 1 FROM reconciliations WHERE account_id=? AND status='draft' LIMIT 1",
                (account_id,),
            ).fetchone()
            is not None
        )

    def create(self, account_id: int, closing_date: str, opening: int, closing: int):
        cursor = self.conn.execute(
            """INSERT INTO reconciliations(account_id, closing_date, opening_balance_cents,
            closing_balance_cents) VALUES (?, ?, ?, ?) RETURNING id""",
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
                AND transaction_id IS NOT DISTINCT FROM ? AND transfer_id IS NOT DISTINCT FROM ?""",
                (statement["id"], transaction_id, transfer_id),
            )

    def complete(self, ident: int):
        self.conn.execute(
            """UPDATE reconciliations SET status='completed',
            completed_at=? WHERE id=?""",
            (datetime.now(UTC).isoformat(), ident),
        )

    def cancel(self, ident: int):
        self.conn.execute("DELETE FROM reconciliation_entries WHERE reconciliation_id=?", (ident,))
        self.conn.execute("DELETE FROM reconciliations WHERE id=?", (ident,))
