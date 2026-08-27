from datetime import date, timedelta

from ..domain.recurrence import add_months
from .account_repository import AccountRepository
from .base_repository import BaseRepository
from .budget_repository import BudgetRepository


class ReportRepository(BaseRepository):
    def __init__(self, connection):
        super().__init__(connection)
        self.accounts = AccountRepository(connection)
        self.budgets = BudgetRepository(connection)

    def dashboard(self, days: int = 30):
        summary = {"income": 0.0, "expense": 0.0}
        for row in self.conn.execute(
            "SELECT type, COALESCE(SUM(amount),0) total FROM transactions GROUP BY type"
        ):
            summary[row["type"]] = float(row["total"] or 0)

        balance_row = self.conn.execute(
            """
            SELECT COALESCE((SELECT SUM(opening_balance) FROM accounts),0)
                 + COALESCE((SELECT SUM(CASE WHEN type='income' THEN amount ELSE -amount END)
                             FROM transactions WHERE account_id IN (SELECT id FROM accounts)),0)
                 + COALESCE((SELECT SUM(amount) FROM transfers
                             WHERE to_account_id IN (SELECT id FROM accounts)),0)
                 - COALESCE((SELECT SUM(amount) FROM transfers
                             WHERE from_account_id IN (SELECT id FROM accounts)),0)
                 AS balance
            """
        ).fetchone()
        balance = float(balance_row["balance"] or 0)

        expenses = [
            {"category": row["category"], "total": float(row["total"] or 0)}
            for row in self.conn.execute(
                """
                SELECT category, SUM(amount) total
                FROM transactions
                WHERE type='expense'
                GROUP BY category
                ORDER BY total DESC
                """
            )
        ]

        start = date.today() - timedelta(days=max(1, days))
        opening = self.conn.execute(
            """
            SELECT COALESCE((SELECT SUM(opening_balance) FROM accounts),0)
                 + COALESCE((SELECT SUM(CASE WHEN type='income' THEN amount ELSE -amount END)
                             FROM transactions WHERE date < ? AND account_id IN
                             (SELECT id FROM accounts)),0)
                 + COALESCE((SELECT SUM(amount) FROM transfers WHERE date < ? AND to_account_id IN
                             (SELECT id FROM accounts)),0)
                 - COALESCE((SELECT SUM(amount) FROM transfers WHERE date < ? AND from_account_id IN
                             (SELECT id FROM accounts)),0)
                 AS balance
            """,
            (start.isoformat(), start.isoformat(), start.isoformat()),
        ).fetchone()["balance"]

        running = float(opening or 0)
        history = []
        daily = self.conn.execute(
            """
            SELECT date, SUM(change) change
            FROM (
                SELECT date, SUM(CASE WHEN type='income' THEN amount ELSE -amount END) change
                FROM transactions
                WHERE date >= ? AND account_id IN (SELECT id FROM accounts)
                GROUP BY date
                UNION ALL
                SELECT date, -SUM(amount) change
                FROM transfers
                WHERE date >= ? AND from_account_id IN (SELECT id FROM accounts)
                GROUP BY date
                UNION ALL
                SELECT date, SUM(amount) change
                FROM transfers
                WHERE date >= ? AND to_account_id IN (SELECT id FROM accounts)
                GROUP BY date
            )
            GROUP BY date
            ORDER BY date
            """,
            (start.isoformat(), start.isoformat(), start.isoformat()),
        ).fetchall()
        for row in daily:
            running += float(row["change"] or 0)
            history.append({"date": row["date"], "balance": round(running, 2)})

        recent = [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT t.*, a.name AS account_name
                FROM transactions t
                LEFT JOIN accounts a ON a.id=t.account_id
                ORDER BY t.date DESC, t.id DESC LIMIT 8
                """
            )
        ]

        return {
            "balance": round(balance, 2),
            "income": round(summary["income"], 2),
            "expenses": round(summary["expense"], 2),
            "net": round(summary["income"] - summary["expense"], 2),
            "expense_categories": expenses,
            "balance_history": history,
            "recent_transactions": recent,
            "budgets": self.budgets.usage(),
            "accounts": self.accounts.list(),
        }

    def monthly(self, months: int = 12):
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
            SELECT strftime('%Y-%m', date) month,
                   SUM(CASE WHEN type='income' THEN amount ELSE 0 END) income,
                   SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) expenses
            FROM transactions
            WHERE strftime('%Y-%m', date) >= ?
            GROUP BY month
            ORDER BY month
            """,
            (start_month,),
        ).fetchall()
        for row in rows:
            if row["month"] not in monthly:
                continue
            income = float(row["income"] or 0)
            expenses = float(row["expenses"] or 0)
            monthly[row["month"]].update(
                {
                    "income": round(income, 2),
                    "expenses": round(expenses, 2),
                    "net": round(income - expenses, 2),
                    "savings_rate": (
                        round(((income - expenses) / income) * 100, 1)
                        if income else 0.0
                    ),
                }
            )

        opening = self.conn.execute(
            """
            SELECT COALESCE((SELECT SUM(opening_balance) FROM accounts),0)
                 + COALESCE((SELECT SUM(CASE WHEN type='income' THEN amount ELSE -amount END)
                             FROM transactions WHERE strftime('%Y-%m', date) < ?),0)
                 + COALESCE((SELECT SUM(amount) FROM transfers WHERE strftime('%Y-%m', date) < ?),0)
                 - COALESCE((SELECT SUM(amount) FROM transfers WHERE strftime('%Y-%m', date) < ?),0)
                 AS balance
            """,
            (start_month, start_month, start_month),
        ).fetchone()["balance"]
        running = float(opening or 0)
        changes = {
            row["month"]: float(row["change"] or 0)
            for row in self.conn.execute(
                """
                SELECT month, SUM(change) change
                FROM (
                    SELECT strftime('%Y-%m', date) month,
                           SUM(CASE WHEN type='income' THEN amount ELSE -amount END) change
                    FROM transactions
                    WHERE strftime('%Y-%m', date) >= ?
                    GROUP BY month
                    UNION ALL
                    SELECT strftime('%Y-%m', date) month, -SUM(amount) change
                    FROM transfers
                    WHERE strftime('%Y-%m', date) >= ?
                    GROUP BY month
                    UNION ALL
                    SELECT strftime('%Y-%m', date) month, SUM(amount) change
                    FROM transfers
                    WHERE strftime('%Y-%m', date) >= ?
                    GROUP BY month
                )
                GROUP BY month
                """,
                (start_month, start_month, start_month),
            )
        }
        for label in labels:
            running += changes.get(label, 0.0)
            monthly[label]["balance"] = round(running, 2)

        category_rows = self.conn.execute(
            """
            SELECT category, SUM(amount) total
            FROM transactions
            WHERE type='expense' AND strftime('%Y-%m', date) >= ?
            GROUP BY category
            ORDER BY total DESC
            LIMIT 10
            """,
            (start_month,),
        ).fetchall()
        top_categories = [
            {"category": row["category"], "total": round(float(row["total"] or 0), 2)}
            for row in category_rows
        ]
        top_category_names = [row["category"] for row in top_categories[:5]]
        trend_totals = self._category_trends(start_month, top_category_names)
        category_trends = [
            {
                "category": category,
                "totals": [trend_totals.get((label, category), 0.0) for label in labels],
            }
            for category in top_category_names
        ]

        series = list(monthly.values())
        total_income = round(sum(row["income"] for row in series), 2)
        total_expenses = round(sum(row["expenses"] for row in series), 2)
        net = round(total_income - total_expenses, 2)
        return {
            "months": series,
            "top_categories": top_categories,
            "category_trends": category_trends,
            "summary": {
                "income": total_income,
                "expenses": total_expenses,
                "net": net,
                "savings_rate": round((net / total_income) * 100, 1) if total_income else 0.0,
            },
        }

    def _category_trends(self, start_month: str, categories: list[str]):
        if not categories:
            return {}
        placeholders = ",".join("?" for _ in categories)
        return {
            (row["month"], row["category"]): round(float(row["total"] or 0), 2)
            for row in self.conn.execute(
                f"""
                SELECT strftime('%Y-%m', date) month, category, SUM(amount) total
                FROM transactions
                WHERE type='expense'
                  AND strftime('%Y-%m', date) >= ?
                  AND category IN ({placeholders})
                GROUP BY month, category
                """,
                (start_month, *categories),
            ).fetchall()
        }
