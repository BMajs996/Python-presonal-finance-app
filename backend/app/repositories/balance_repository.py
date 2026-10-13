from ..domain import business_date
from ..domain.date_range import DateRange
from .base_repository import BaseRepository


class BalanceRepository(BaseRepository):
    def total_cents(self) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE((
                       SELECT SUM(opening_balance_cents)
                       FROM accounts WHERE currency=? AND user_id=?
                   ), 0)
                 + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income'
                                       THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t
                       JOIN accounts a ON a.id=t.account_id
                       WHERE t.deleted_at IS NULL AND a.currency=? AND t.date<=? AND a.user_id=?
                   ), 0) AS balance_cents
            """,
            (
                self.base_currency,
                self.user_id,
                self.base_currency,
                business_date.today().isoformat(),
                self.user_id,
            ),
        ).fetchone()
        return int(row["balance_cents"] or 0)

    def daily_history_cents(self, period: DateRange):
        opening = self.conn.execute(
            """
            SELECT COALESCE((
                       SELECT SUM(opening_balance_cents)
                       FROM accounts WHERE currency=? AND user_id=?
                   ), 0)
                 + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income'
                                       THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t
                       JOIN accounts a ON a.id=t.account_id
                       WHERE t.deleted_at IS NULL AND t.date < ? AND a.currency=? AND a.user_id=?
                   ), 0) AS balance_cents
            """,
            (self.base_currency, self.user_id, period.start_iso, self.base_currency, self.user_id),
        ).fetchone()["balance_cents"]
        daily = self.conn.execute(
            """
            SELECT t.date,
                   SUM(CASE WHEN t.type='income'
                            THEN t.amount_cents ELSE -t.amount_cents END) change_cents
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            WHERE t.deleted_at IS NULL AND t.date BETWEEN ? AND ? AND a.currency=? AND a.user_id=?
            GROUP BY t.date
            ORDER BY t.date
            """,
            (period.start_iso, period.end_iso, self.base_currency, self.user_id),
        ).fetchall()
        return int(opening or 0), [dict(row) for row in daily]

    def monthly_history_cents(self, labels: list[str]):
        start_month = labels[0] + "-01"
        opening = self.conn.execute(
            """
            SELECT COALESCE((
                       SELECT SUM(opening_balance_cents)
                       FROM accounts WHERE currency=? AND user_id=?
                   ), 0)
                 + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income'
                                       THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t
                       JOIN accounts a ON a.id=t.account_id
                       WHERE t.deleted_at IS NULL AND t.date < ? AND a.currency=? AND a.user_id=?
                   ), 0) AS balance_cents
            """,
            (self.base_currency, self.user_id, start_month, self.base_currency, self.user_id),
        ).fetchone()["balance_cents"]
        changes = {
            row["month"]: int(row["change_cents"] or 0)
            for row in self.conn.execute(
                """
                SELECT substr(t.date, 1, 7) AS month,
                       SUM(CASE WHEN t.type='income'
                                THEN t.amount_cents ELSE -t.amount_cents END) change_cents
                FROM transactions t
                JOIN accounts a ON a.id=t.account_id
                WHERE t.deleted_at IS NULL AND t.date >= ? AND t.date<=? AND a.currency=? AND a.user_id=?
                GROUP BY month
                """,
                (start_month, business_date.today().isoformat(), self.base_currency, self.user_id),
            )
        }
        return int(opening or 0), changes
