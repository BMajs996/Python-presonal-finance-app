import calendar
import csv
import os
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


TRANSACTION_TYPES = ("income", "expense")
FREQUENCIES = ("daily", "weekly", "monthly", "yearly")


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def calculate_next_date(frequency: str, current: date) -> date:
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "monthly":
        return add_months(current, 1)
    if frequency == "yearly":
        try:
            return current.replace(year=current.year + 1)
        except ValueError:
            # Feb 29 -> Feb 28 in non-leap years.
            return current.replace(year=current.year + 1, day=28)
    raise ValueError(f"Unsupported frequency: {frequency}")


class FinanceDatabase:
    """Persistence layer compatible with the original desktop database."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._process_recurring_transactions()

    def _create_tables(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                type TEXT,
                category TEXT,
                amount REAL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS recurring_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                category TEXT,
                amount REAL,
                description TEXT,
                frequency TEXT,
                next_date TEXT,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT UNIQUE,
                monthly_limit REAL,
                month_year TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.conn.commit()

    def _process_recurring_transactions(self):
        today = date.today()
        rows = self.conn.execute(
            """
            SELECT id, type, category, amount, description, frequency, next_date
            FROM recurring_transactions
            WHERE active = 1 AND next_date <= ?
            ORDER BY next_date
            """,
            (today.isoformat(),),
        ).fetchall()

        with self.conn:
            for row in rows:
                occurrence = date.fromisoformat(row["next_date"])
                guard = 0
                while occurrence <= today:
                    self.conn.execute(
                        """
                        INSERT INTO transactions
                            (date, type, category, amount, description)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            occurrence.isoformat(),
                            row["type"],
                            row["category"],
                            row["amount"],
                            f'{row["description"]} (Auto)'.strip(),
                        ),
                    )
                    occurrence = calculate_next_date(row["frequency"], occurrence)
                    guard += 1
                    if guard > 10000:
                        raise RuntimeError(
                            f"Recurring transaction {row['id']} produced too many occurrences."
                        )

                self.conn.execute(
                    "UPDATE recurring_transactions SET next_date = ? WHERE id = ?",
                    (occurrence.isoformat(), row["id"]),
                )

    # ---------- Transactions ----------

    def list_transactions(
        self,
        search: str = "",
        category: str = "",
        type_: str = "",
        date_start: str = "",
        date_end: str = "",
        limit: int = 100,
        offset: int = 0,
    ):
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []

        if search:
            query += " AND (description LIKE ? OR category LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        if category:
            query += " AND category = ?"
            params.append(category)
        if type_:
            query += " AND type = ?"
            params.append(type_)
        if date_start:
            query += " AND date >= ?"
            params.append(date_start)
        if date_end:
            query += " AND date <= ?"
            params.append(date_end)

        count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
        total = self.conn.execute(count_query, params).fetchone()[0]

        query += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
        rows = self.conn.execute(query, [*params, limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def get_transaction(self, transaction_id: int):
        row = self.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_transaction(self, payload):
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO transactions(date, type, category, amount, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                ),
            )
        return self.get_transaction(cur.lastrowid)

    def update_transaction(self, transaction_id: int, payload):
        with self.conn:
            self.conn.execute(
                """
                UPDATE transactions
                SET date=?, type=?, category=?, amount=?, description=?
                WHERE id=?
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    transaction_id,
                ),
            )
        return self.get_transaction(transaction_id)

    def delete_transaction(self, transaction_id: int):
        with self.conn:
            self.conn.execute(
                "DELETE FROM transactions WHERE id=?", (transaction_id,)
            )

    # ---------- Dashboard ----------

    def dashboard(self, days: int = 30):
        summary = {
            "income": 0.0,
            "expense": 0.0,
        }
        for row in self.conn.execute(
            "SELECT type, COALESCE(SUM(amount),0) total FROM transactions GROUP BY type"
        ):
            summary[row["type"]] = float(row["total"] or 0)

        balance_row = self.conn.execute(
            """
            SELECT COALESCE(SUM(
                CASE WHEN type='income' THEN amount ELSE -amount END
            ),0) balance
            FROM transactions
            """
        ).fetchone()
        balance = float(balance_row["balance"] or 0)

        expenses = [
            {"category": r["category"], "total": float(r["total"] or 0)}
            for r in self.conn.execute(
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
            SELECT COALESCE(SUM(
                CASE WHEN type='income' THEN amount ELSE -amount END
            ),0) balance
            FROM transactions WHERE date < ?
            """,
            (start.isoformat(),),
        ).fetchone()["balance"]

        running = float(opening or 0)
        history = []
        daily = self.conn.execute(
            """
            SELECT date,
                   SUM(CASE WHEN type='income' THEN amount ELSE -amount END) change
            FROM transactions
            WHERE date >= ?
            GROUP BY date
            ORDER BY date
            """,
            (start.isoformat(),),
        ).fetchall()

        for row in daily:
            running += float(row["change"] or 0)
            history.append({"date": row["date"], "balance": round(running, 2)})

        recent = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM transactions ORDER BY date DESC, id DESC LIMIT 8"
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
            "budgets": self.get_budget_usage(),
        }

    # ---------- Categories ----------

    def categories(self):
        return [
            r["category"]
            for r in self.conn.execute(
                "SELECT DISTINCT category FROM transactions ORDER BY category"
            )
        ]

    # ---------- Recurring ----------

    def recurring(self):
        return [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT * FROM recurring_transactions
                WHERE active=1 ORDER BY next_date
                """
            )
        ]

    def add_recurring(self, payload):
        next_date = calculate_next_date(payload.frequency, payload.start_date)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO recurring_transactions
                    (type, category, amount, description, frequency, next_date, active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    payload.frequency,
                    next_date.isoformat(),
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM recurring_transactions WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)

    def delete_recurring(self, recurring_id: int):
        with self.conn:
            self.conn.execute(
                "UPDATE recurring_transactions SET active=0 WHERE id=?",
                (recurring_id,),
            )

    # ---------- Budgets ----------

    def get_budget_usage(self):
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
        for r in rows:
            limit = float(r["monthly_limit"])
            spent = float(r["spent"] or 0)
            result.append(
                {
                    "id": r["id"],
                    "category": r["category"],
                    "monthly_limit": limit,
                    "month_year": r["month_year"],
                    "spent": spent,
                    "percentage": round((spent / limit) * 100, 1) if limit else 0,
                }
            )
        return result

    def add_budget(self, payload):
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
            b for b in self.get_budget_usage() if b["category"] == payload.category.strip()
        )

    def delete_budget(self, budget_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM budgets WHERE id=?", (budget_id,))

    def close(self):
        self.conn.close()
