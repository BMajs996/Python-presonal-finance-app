import calendar
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .migrations import migrate

TRANSACTION_TYPES = ("income", "expense")
FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
ACCOUNT_TYPES = ("checking", "savings", "cash", "credit_card", "investment", "other")


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
            return current.replace(year=current.year + 1, day=28)
    raise ValueError(f"Unsupported frequency: {frequency}")


class FinanceDatabase:
    """SQLite persistence layer, including migrations for the legacy database."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._process_recurring_transactions()

    def _create_tables(self):
        # Legacy tables are created first so the migration can safely upgrade
        # an existing desktop database or initialize a fresh database.
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
        migrate(self.conn)
        self.conn.commit()

    # ---------- Shared helpers ----------

    def _default_account_id(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE name='Main Account' LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("Main Account is missing")
        return int(row["id"])

    def _resolve_account_id(self, account_id: int | None) -> int:
        resolved = self._default_account_id() if account_id is None else account_id
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE id=? AND active=1", (resolved,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account {resolved} does not exist or is inactive")
        return resolved

    def _account_row(self, account_id: int):
        row = self.conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return dict(row) if row else None

    # ---------- Recurring processing ----------

    def _process_recurring_transactions(self):
        today = date.today()
        rows = self.conn.execute(
            """
            SELECT id, type, category, amount, description, frequency, next_date, account_id
            FROM recurring_transactions
            WHERE active=1 AND next_date <= ?
            ORDER BY next_date, id
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
                            (date, type, category, amount, description, account_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            occurrence.isoformat(),
                            row["type"],
                            row["category"],
                            row["amount"],
                            f'{row["description"]} (Auto)'.strip(),
                            row["account_id"] or self._default_account_id(),
                        ),
                    )
                    occurrence = calculate_next_date(row["frequency"], occurrence)
                    guard += 1
                    if guard > 10000:
                        raise RuntimeError(
                            f"Recurring transaction {row['id']} produced too many occurrences."
                        )

                self.conn.execute(
                    "UPDATE recurring_transactions SET next_date=? WHERE id=?",
                    (occurrence.isoformat(), row["id"]),
                )

    # ---------- Accounts ----------

    def list_accounts(self, include_inactive: bool = False):
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

    def get_account(self, account_id: int):
        rows = self.list_accounts(include_inactive=True)
        return next((row for row in rows if row["id"] == account_id), None)

    def add_account(self, payload):
        name = payload.name.strip()
        if not name:
            raise ValueError("Account name is required")
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO accounts(name, type, currency, opening_balance, active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (
                    name,
                    payload.type,
                    payload.currency.upper(),
                    payload.opening_balance,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return self.get_account(cur.lastrowid)

    def deactivate_account(self, account_id: int):
        if account_id == self._default_account_id():
            raise ValueError("Main Account cannot be deactivated")
        with self.conn:
            self.conn.execute("UPDATE accounts SET active=0 WHERE id=?", (account_id,))

    # ---------- Transactions ----------

    def list_transactions(
        self,
        search: str = "",
        category: str = "",
        type_: str = "",
        account_id: int | None = None,
        date_start: str = "",
        date_end: str = "",
        limit: int = 100,
        offset: int = 0,
    ):
        query = """
            SELECT t.*, a.name AS account_name
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            WHERE 1=1
        """
        params = []
        if search:
            query += " AND (t.description LIKE ? OR t.category LIKE ? OR a.name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if category:
            query += " AND t.category=?"
            params.append(category)
        if type_:
            query += " AND t.type=?"
            params.append(type_)
        if account_id is not None:
            query += " AND t.account_id=?"
            params.append(account_id)
        if date_start:
            query += " AND t.date>=?"
            params.append(date_start)
        if date_end:
            query += " AND t.date<=?"
            params.append(date_end)

        count_query = f"SELECT COUNT(*) FROM ({query})"
        total = self.conn.execute(count_query, params).fetchone()[0]
        query += " ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?"
        rows = self.conn.execute(query, [*params, limit, offset]).fetchall()
        return [dict(row) for row in rows], total

    def get_transaction(self, transaction_id: int):
        row = self.conn.execute(
            """
            SELECT t.*, a.name AS account_name
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            WHERE t.id=?
            """,
            (transaction_id,),
        ).fetchone()
        return dict(row) if row else None

    def add_transaction(self, payload):
        account_id = self._resolve_account_id(payload.account_id)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO transactions(date, type, category, amount, description, account_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    account_id,
                ),
            )
        return self.get_transaction(cur.lastrowid)

    def update_transaction(self, transaction_id: int, payload):
        existing = self.get_transaction(transaction_id)
        if not existing:
            return None
        account_id = (
            self._resolve_account_id(payload.account_id)
            if payload.account_id is not None
            else existing["account_id"]
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE transactions
                SET date=?, type=?, category=?, amount=?, description=?, account_id=?
                WHERE id=?
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    account_id,
                    transaction_id,
                ),
            )
        return self.get_transaction(transaction_id)

    def delete_transaction(self, transaction_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))

    # ---------- Transfers ----------

    def list_transfers(self, limit: int = 100, offset: int = 0):
        rows = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            ORDER BY t.date DESC, t.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_transfer(self, payload):
        if payload.from_account_id == payload.to_account_id:
            raise ValueError("Transfer accounts must be different")
        self._resolve_account_id(payload.from_account_id)
        self._resolve_account_id(payload.to_account_id)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO transfers(date, from_account_id, to_account_id, amount, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.from_account_id,
                    payload.to_account_id,
                    payload.amount,
                    payload.description.strip(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        row = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            WHERE t.id=?
            """,
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)

    def get_transfer(self, transfer_id: int):
        row = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            WHERE t.id=?
            """,
            (transfer_id,),
        ).fetchone()
        return dict(row) if row else None

    def delete_transfer(self, transfer_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM transfers WHERE id=?", (transfer_id,))

    # ---------- Dashboard ----------

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
                 + COALESCE((SELECT SUM(amount) FROM transfers WHERE to_account_id IN (SELECT id FROM accounts)),0)
                 - COALESCE((SELECT SUM(amount) FROM transfers WHERE from_account_id IN (SELECT id FROM accounts)),0)
                 AS balance
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
            dict(r)
            for r in self.conn.execute(
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
            "budgets": self.get_budget_usage(),
            "accounts": self.list_accounts(),
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
                SELECT r.*, a.name AS account_name
                FROM recurring_transactions r
                LEFT JOIN accounts a ON a.id=r.account_id
                WHERE r.active=1 ORDER BY r.next_date
                """
            )
        ]

    def add_recurring(self, payload):
        account_id = self._resolve_account_id(payload.account_id)
        next_date = calculate_next_date(payload.frequency, payload.start_date)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO recurring_transactions
                    (type, category, amount, description, frequency, next_date, active, account_id)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    payload.frequency,
                    next_date.isoformat(),
                    account_id,
                ),
            )
        row = self.conn.execute(
            """
            SELECT r.*, a.name AS account_name
            FROM recurring_transactions r
            LEFT JOIN accounts a ON a.id=r.account_id
            WHERE r.id=?
            """,
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)

    def delete_recurring(self, recurring_id: int):
        with self.conn:
            self.conn.execute("UPDATE recurring_transactions SET active=0 WHERE id=?", (recurring_id,))

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
        return next(b for b in self.get_budget_usage() if b["category"] == payload.category.strip())

    def delete_budget(self, budget_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM budgets WHERE id=?", (budget_id,))

    def close(self):
        self.conn.close()
