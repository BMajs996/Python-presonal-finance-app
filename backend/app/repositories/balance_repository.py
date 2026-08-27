from datetime import date, timedelta

from .base_repository import BaseRepository


class BalanceRepository(BaseRepository):
    def total_cents(self) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE((
                       SELECT SUM(opening_balance_cents)
                       FROM accounts WHERE currency=?
                   ), 0)
                 + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income'
                                       THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t
                       JOIN accounts a ON a.id=t.account_id
                       WHERE a.currency=?
                   ), 0) AS balance_cents
            """,
            (self.base_currency, self.base_currency),
        ).fetchone()
        return int(row["balance_cents"] or 0)

    def daily_history_cents(self, days: int):
        start = date.today() - timedelta(days=max(1, days))
        opening = self.conn.execute(
            """
            SELECT COALESCE((
                       SELECT SUM(opening_balance_cents)
                       FROM accounts WHERE currency=?
                   ), 0)
                 + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income'
                                       THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t
                       JOIN accounts a ON a.id=t.account_id
                       WHERE t.date < ? AND a.currency=?
                   ), 0) AS balance_cents
            """,
            (self.base_currency, start.isoformat(), self.base_currency),
        ).fetchone()["balance_cents"]
        daily = self.conn.execute(
            """
            SELECT t.date,
                   SUM(CASE WHEN t.type='income'
                            THEN t.amount_cents ELSE -t.amount_cents END) change_cents
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            WHERE t.date >= ? AND a.currency=?
            GROUP BY t.date
            ORDER BY t.date
            """,
            (start.isoformat(), self.base_currency),
        ).fetchall()
        return int(opening or 0), [dict(row) for row in daily]

    def monthly_history_cents(self, labels: list[str]):
        start_month = labels[0]
        opening = self.conn.execute(
            """
            SELECT COALESCE((
                       SELECT SUM(opening_balance_cents)
                       FROM accounts WHERE currency=?
                   ), 0)
                 + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income'
                                       THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t
                       JOIN accounts a ON a.id=t.account_id
                       WHERE strftime('%Y-%m', t.date) < ? AND a.currency=?
                   ), 0) AS balance_cents
            """,
            (self.base_currency, start_month, self.base_currency),
        ).fetchone()["balance_cents"]
        changes = {
            row["month"]: int(row["change_cents"] or 0)
            for row in self.conn.execute(
                """
                SELECT strftime('%Y-%m', t.date) month,
                       SUM(CASE WHEN t.type='income'
                                THEN t.amount_cents ELSE -t.amount_cents END) change_cents
                FROM transactions t
                JOIN accounts a ON a.id=t.account_id
                WHERE strftime('%Y-%m', t.date) >= ? AND a.currency=?
                GROUP BY month
                """,
                (start_month, self.base_currency),
            )
        }
        return int(opening or 0), changes
