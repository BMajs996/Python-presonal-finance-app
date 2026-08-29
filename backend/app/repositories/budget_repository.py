from datetime import date

from ..domain.money import Money
from .base_repository import BaseRepository


class BudgetRepository(BaseRepository):
    def usage(self):
        month = date.today().strftime("%Y-%m")
        rows = self.conn.execute(
            """
            SELECT b.id, b.category, b.monthly_limit_cents, b.month_year,
                   COALESCE(SUM(t.amount_cents),0) spent_cents
            FROM budgets b
            LEFT JOIN transactions t
              ON t.category=b.category
             AND t.type='expense'
             AND strftime('%Y-%m', t.date)=?
            WHERE b.month_year=?
            GROUP BY b.id, b.category, b.monthly_limit_cents, b.month_year
            ORDER BY b.category
            """,
            (month, month),
        ).fetchall()
        result = []
        for row in rows:
            limit = Money(row["monthly_limit_cents"], self.base_currency)
            spent = Money(row["spent_cents"] or 0, self.base_currency)
            result.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "monthly_limit": limit.as_float(),
                    "currency": self.base_currency,
                    "month_year": row["month_year"],
                    "spent": spent.as_float(),
                    "percentage": (round((spent.cents / limit.cents) * 100, 1) if limit.cents else 0),
                }
            )
        return result

    def add(self, payload):
        month = date.today().strftime("%Y-%m")
        limit = Money.from_amount(payload.monthly_limit, self.base_currency)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO budgets(category, monthly_limit, monthly_limit_cents, month_year)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET
                    monthly_limit=excluded.monthly_limit,
                    monthly_limit_cents=excluded.monthly_limit_cents,
                    month_year=excluded.month_year
                """,
                (payload.category.strip(), limit.as_float(), limit.cents, month),
            )
        return next(budget for budget in self.usage() if budget["category"] == payload.category.strip())

    def update(self, budget_id: int, payload):
        month = date.today().strftime("%Y-%m")
        limit = Money.from_amount(payload.monthly_limit, self.base_currency)
        if not self.conn.execute("SELECT id FROM budgets WHERE id=?", (budget_id,)).fetchone():
            return None
        with self.conn:
            self.conn.execute(
                """
                UPDATE budgets
                SET category=?, monthly_limit=?, monthly_limit_cents=?, month_year=?
                WHERE id=?
                """,
                (
                    payload.category.strip(),
                    limit.as_float(),
                    limit.cents,
                    month,
                    budget_id,
                ),
            )
        return next(
            (budget for budget in self.usage() if budget["id"] == budget_id),
            None,
        )

    def delete(self, budget_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM budgets WHERE id=?", (budget_id,))
