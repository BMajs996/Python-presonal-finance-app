from datetime import UTC, datetime

from .base_repository import BaseRepository


class AccountRepository(BaseRepository):
    def list(self, include_inactive: bool = False):
        where = "" if include_inactive else "WHERE a.active=1"
        rows = self.conn.execute(
            f"""
            SELECT a.id, a.name, a.type, a.currency, a.opening_balance, a.active,
                   a.created_at,
                   a.opening_balance
                   + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE -t.amount END)
                       FROM transactions t WHERE t.account_id=a.id
                   ), 0)
                   + COALESCE((
                       SELECT SUM(t.amount) FROM transfers t WHERE t.to_account_id=a.id
                   ), 0)
                   - COALESCE((
                       SELECT SUM(t.amount) FROM transfers t WHERE t.from_account_id=a.id
                   ), 0) AS balance,
                   (SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.id) AS transaction_count
            FROM accounts a
            {where}
            ORDER BY a.active DESC, a.name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, account_id: int):
        return next(
            (row for row in self.list(include_inactive=True) if row["id"] == account_id),
            None,
        )

    def add(self, payload):
        name = payload.name.strip()
        if not name:
            raise ValueError("Account name is required")
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO accounts(name, type, currency, opening_balance, active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    name,
                    payload.type,
                    payload.currency.upper(),
                    payload.opening_balance,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.get(cursor.lastrowid)

    def deactivate(self, account_id: int):
        if account_id == self.default_account_id():
            raise ValueError("Main Account cannot be deactivated")
        with self.conn:
            self.conn.execute("UPDATE accounts SET active=0 WHERE id=?", (account_id,))
