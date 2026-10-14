from ..domain import business_date
from ..domain.money import Money, money_contract
from .base_repository import BaseRepository


class BudgetRepository(BaseRepository):
    def usage(self, budget_id: int | None = None):
        today = business_date.today()
        month = today.strftime("%Y-%m")
        conditions = "b.month_year=? AND b.user_id=?"
        params: list[str | int] = [
            self.user_id,
            today.replace(day=1).isoformat(),
            today.isoformat(),
            month,
            self.user_id,
        ]
        if budget_id is not None:
            conditions += " AND b.id=?"
            params.append(budget_id)
        # Only fixed predicates are interpolated; identifiers and dates stay bound.
        query = f"""
            SELECT b.id, b.category, b.monthly_limit_cents, b.month_year,
                   COALESCE(SUM(t.amount_cents),0) spent_cents
            FROM budgets b
            LEFT JOIN transactions t
              ON t.category=b.category AND t.deleted_at IS NULL
             AND t.account_id IN (SELECT id FROM accounts WHERE user_id=?)
             AND t.type='expense'
             AND t.date BETWEEN ? AND ?
            WHERE {conditions}
            GROUP BY b.id, b.category, b.monthly_limit_cents, b.month_year
            ORDER BY b.category
            """
        rows = self.conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            limit = Money(row["monthly_limit_cents"], self.base_currency)
            spent = Money(int(row["spent_cents"] or 0), self.base_currency)
            result.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "monthly_limit": limit.as_float(),
                    "currency": self.base_currency,
                    "month_year": row["month_year"],
                    "spent": spent.as_float(),
                    "money": money_contract(self.base_currency, monthly_limit=limit.cents, spent=spent.cents),
                    "percentage": (round((spent.cents / limit.cents) * 100, 1) if limit.cents else 0),
                }
            )
        return result

    def add(self, payload):
        month = business_date.today().strftime("%Y-%m")
        limit = Money.from_amount(payload.monthly_limit, self.base_currency)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO budgets(category, monthly_limit, monthly_limit_cents, month_year, user_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id,category) DO UPDATE SET
                    monthly_limit=excluded.monthly_limit,
                    monthly_limit_cents=excluded.monthly_limit_cents,
                    month_year=excluded.month_year
                RETURNING id
                """,
                (payload.category.strip(), limit.as_float(), limit.cents, month, self.user_id),
            )
            budget_id = self.inserted_id(cursor)
        return self.usage(budget_id)[0]

    def update(self, budget_id: int, payload):
        month = business_date.today().strftime("%Y-%m")
        limit = Money.from_amount(payload.monthly_limit, self.base_currency)
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE budgets
                SET category=?, monthly_limit=?, monthly_limit_cents=?, month_year=?
                WHERE id=? AND user_id=? RETURNING id
                """,
                (
                    payload.category.strip(),
                    limit.as_float(),
                    limit.cents,
                    month,
                    budget_id,
                    self.user_id,
                ),
            )
            if cursor.fetchone() is None:
                return None
        return next(iter(self.usage(budget_id)), None)

    def delete(self, budget_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM budgets WHERE id=? AND user_id=?", (budget_id, self.user_id))
