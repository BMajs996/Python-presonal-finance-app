from datetime import date

from .base_repository import BaseRepository


class BudgetRepository(BaseRepository):
    def usage(self):
        month = date.today().strftime("%Y-%m")
        rows = self.conn.execute(
            """
            SELECT b.id, b.category, b.monthly_limit, b.month_year,
                   COALESCE(SUM(t.amount),0) spent
            FROM budgets b
            LEFT JOIN transactions t
              ON t.category=b.category
             AND t.type='expense'
             AND strftime('%Y-%m', t.date)=?
            WHERE b.month_year=?
            GROUP BY b.id, b.category, b.monthly_limit, b.month_year
            ORDER BY b.category
            """,
            (month, month),
        ).fetchall()
        result = []
        for row in rows:
            limit = float(row["monthly_limit"])
            spent = float(row["spent"] or 0)
            result.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "monthly_limit": limit,
                    "month_year": row["month_year"],
                    "spent": spent,
                    "percentage": round((spent / limit) * 100, 1) if limit else 0,
                }
            )
        return result

    def add(self, payload):
        month = date.today().strftime("%Y-%m")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO budgets(category, monthly_limit, month_year)
                VALUES (?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET
                    monthly_limit=excluded.monthly_limit,
                    month_year=excluded.month_year
                """,
                (payload.category.strip(), payload.monthly_limit, month),
            )
        return next(
            budget for budget in self.usage()
            if budget["category"] == payload.category.strip()
        )

    def update(self, budget_id: int, payload):
        month = date.today().strftime("%Y-%m")
        if not self.conn.execute(
            "SELECT id FROM budgets WHERE id=?", (budget_id,)
        ).fetchone():
            return None
        with self.conn:
            self.conn.execute(
                """
                UPDATE budgets
                SET category=?, monthly_limit=?, month_year=?
                WHERE id=?
                """,
                (payload.category.strip(), payload.monthly_limit, month, budget_id),
            )
        return next(
            (budget for budget in self.usage() if budget["id"] == budget_id),
            None,
        )

    def delete(self, budget_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM budgets WHERE id=?", (budget_id,))
