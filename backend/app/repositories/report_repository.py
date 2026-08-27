from datetime import date

from ..domain.money import Money
from ..domain.recurrence import add_months
from .account_repository import AccountRepository
from .base_repository import BaseRepository
from .budget_repository import BudgetRepository
from .transaction_repository import TransactionRepository


class ReportRepository(BaseRepository):
    def __init__(self, connection, base_currency: str = "USD"):
        super().__init__(connection, base_currency)
        self.accounts = AccountRepository(connection, base_currency)
        self.budgets = BudgetRepository(connection, base_currency)
        self.transactions = TransactionRepository(connection, base_currency)

    def dashboard_data(self):
        summary = {"income": 0, "expense": 0}
        for row in self.conn.execute(
            """
            SELECT t.type, COALESCE(SUM(t.amount_cents),0) total_cents
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            WHERE a.currency=?
            GROUP BY t.type
            """,
            (self.base_currency,),
        ):
            summary[row["type"]] = int(row["total_cents"] or 0)

        expenses = [
            {
                "category": row["category"],
                "total": Money(row["total_cents"] or 0, self.base_currency).as_float(),
            }
            for row in self.conn.execute(
                """
                SELECT t.category, SUM(t.amount_cents) total_cents
                FROM transactions t
                JOIN accounts a ON a.id=t.account_id
                WHERE t.type='expense' AND a.currency=?
                GROUP BY t.category
                ORDER BY total_cents DESC
                """,
                (self.base_currency,),
            )
        ]
        recent, _ = self.transactions.list(limit=8)
        income = Money(summary["income"], self.base_currency)
        expenses_total = Money(summary["expense"], self.base_currency)
        return {
            "currency": self.base_currency,
            "income": income.as_float(),
            "expenses": expenses_total.as_float(),
            "net": (income - expenses_total).as_float(),
            "expense_categories": expenses,
            "recent_transactions": recent,
            "budgets": self.budgets.usage(),
            "accounts": self.accounts.list(),
        }

    def monthly_data(self, months: int = 12):
        months = min(max(months, 1), 60)
        today = date.today().replace(day=1)
        labels = [
            add_months(today, -offset).strftime("%Y-%m")
            for offset in range(months - 1, -1, -1)
        ]
        start_month = labels[0]
        monthly = {
            label: {
                "month": label,
                "income": 0.0,
                "expenses": 0.0,
                "net": 0.0,
                "savings_rate": 0.0,
                "balance": 0.0,
            }
            for label in labels
        }

        rows = self.conn.execute(
            """
            SELECT strftime('%Y-%m', t.date) month,
                   SUM(CASE WHEN t.type='income' THEN t.amount_cents ELSE 0 END) income_cents,
                   SUM(CASE WHEN t.type='expense' THEN t.amount_cents ELSE 0 END) expense_cents
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            WHERE strftime('%Y-%m', t.date) >= ? AND a.currency=?
            GROUP BY month
            ORDER BY month
            """,
            (start_month, self.base_currency),
        ).fetchall()
        for row in rows:
            if row["month"] not in monthly:
                continue
            income = Money(row["income_cents"] or 0, self.base_currency)
            expenses = Money(row["expense_cents"] or 0, self.base_currency)
            net = income - expenses
            monthly[row["month"]].update(
                {
                    "income": income.as_float(),
                    "expenses": expenses.as_float(),
                    "net": net.as_float(),
                    "savings_rate": (
                        round((net.cents / income.cents) * 100, 1)
                        if income.cents else 0.0
                    ),
                }
            )

        category_rows = self.conn.execute(
            """
            SELECT t.category, SUM(t.amount_cents) total_cents
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            WHERE t.type='expense'
              AND strftime('%Y-%m', t.date) >= ?
              AND a.currency=?
            GROUP BY t.category
            ORDER BY total_cents DESC
            LIMIT 10
            """,
            (start_month, self.base_currency),
        ).fetchall()
        top_categories = [
            {
                "category": row["category"],
                "total": Money(row["total_cents"] or 0, self.base_currency).as_float(),
            }
            for row in category_rows
        ]
        top_category_names = [row["category"] for row in top_categories[:5]]
        trend_totals = self._category_trends(start_month, top_category_names)
        category_trends = [
            {
                "category": category,
                "totals": [
                    Money(trend_totals.get((label, category), 0), self.base_currency).as_float()
                    for label in labels
                ],
            }
            for category in top_category_names
        ]

        series = list(monthly.values())
        total_income = Money(
            sum(
                Money.from_amount(item["income"], self.base_currency).cents
                for item in series
            ),
            self.base_currency,
        )
        total_expenses = Money(
            sum(
                Money.from_amount(item["expenses"], self.base_currency).cents
                for item in series
            ),
            self.base_currency,
        )
        net = total_income - total_expenses
        return {
            "currency": self.base_currency,
            "months": series,
            "top_categories": top_categories,
            "category_trends": category_trends,
            "summary": {
                "income": total_income.as_float(),
                "expenses": total_expenses.as_float(),
                "net": net.as_float(),
                "savings_rate": (
                    round((net.cents / total_income.cents) * 100, 1)
                    if total_income.cents else 0.0
                ),
            },
        }

    def _category_trends(self, start_month: str, categories: list[str]):
        if not categories:
            return {}
        placeholders = ",".join("?" for _ in categories)
        return {
            (row["month"], row["category"]): int(row["total_cents"] or 0)
            for row in self.conn.execute(
                f"""
                SELECT strftime('%Y-%m', t.date) month,
                       t.category,
                       SUM(t.amount_cents) total_cents
                FROM transactions t
                JOIN accounts a ON a.id=t.account_id
                WHERE t.type='expense'
                  AND strftime('%Y-%m', t.date) >= ?
                  AND t.category IN ({placeholders})
                  AND a.currency=?
                GROUP BY month, t.category
                """,
                (start_month, *categories, self.base_currency),
            ).fetchall()
        }
