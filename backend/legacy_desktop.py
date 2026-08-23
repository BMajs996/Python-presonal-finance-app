import csv
import os
import shutil
import sqlite3
import calendar
from datetime import datetime, timedelta
from typing import Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import matplotlib
if os.environ.get("DISPLAY") or os.name == "nt":
    matplotlib.use("TkAgg")
else:
    matplotlib.use("Agg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


# ============================================================
# DOMAIN / VALIDATION HELPERS
# ============================================================

TRANSACTION_TYPES = ("income", "expense")
FREQUENCIES = ("daily", "weekly", "monthly", "yearly")


def today_string() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def current_month_start() -> str:
    return datetime.now().strftime("%Y-%m-01")


def parse_date(value: str, field_name: str = "Date") -> str:
    value = value.strip()
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from exc
    return parsed.strftime("%Y-%m-%d")


def parse_positive_amount(value: str, field_name: str = "Amount") -> float:
    try:
        amount = float(value.replace("$", "").replace(",", "").strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Please enter a valid positive number for {field_name.lower()}.") from exc

    if amount <= 0:
        raise ValueError(f"Please enter a valid positive number for {field_name.lower()}.")
    return amount


def validate_transaction_values(date, type_, category, amount, description=""):
    date = parse_date(date)
    type_ = type_.strip().lower()
    if type_ not in TRANSACTION_TYPES:
        raise ValueError("Transaction type must be income or expense.")

    category = category.strip()
    if not category:
        raise ValueError("Please enter a category.")

    amount = parse_positive_amount(str(amount))
    return date, type_, category, amount, description.strip()


def add_months(value: datetime, months: int) -> datetime:
    """Add calendar months without producing invalid dates such as February 31."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def calculate_next_date(frequency: str, current_date: str) -> str:
    date_obj = datetime.strptime(current_date, "%Y-%m-%d")

    if frequency == "daily":
        next_date = date_obj + timedelta(days=1)
    elif frequency == "weekly":
        next_date = date_obj + timedelta(weeks=1)
    elif frequency == "monthly":
        next_date = add_months(date_obj, 1)
    elif frequency == "yearly":
        # Preserve Feb 29 safely by clamping to Feb 28 in non-leap years.
        target_year = date_obj.year + 1
        day = min(date_obj.day, calendar.monthrange(target_year, date_obj.month)[1])
        next_date = date_obj.replace(year=target_year, day=day)
    else:
        next_date = date_obj + timedelta(days=30)

    return next_date.strftime("%Y-%m-%d")


# ============================================================
# DATABASE / REPOSITORY LAYER
# ============================================================

class FinanceDatabase:
    """SQLite persistence and data-oriented operations.

    The public API intentionally remains compatible with the original
    application, so an existing personal_finance.db can continue to be used.
    """

    def __init__(self, db_name="personal_finance.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._process_recurring_transactions()

    def _execute(self, query, params=()):
        return self.conn.execute(query, params)

    def _create_tables(self):
        self._execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                type TEXT,
                category TEXT,
                amount REAL,
                description TEXT
            )
        """)

        self._execute("""
            CREATE TABLE IF NOT EXISTS recurring_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                category TEXT,
                amount REAL,
                description TEXT,
                frequency TEXT,
                next_date TEXT,
                active INTEGER DEFAULT 1
            )
        """)

        # Keep the original schema for compatibility with existing databases.
        self._execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT UNIQUE,
                monthly_limit REAL,
                month_year TEXT
            )
        """)

        self._execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.commit()

    # ---------------- Recurring transactions ----------------

    def _process_recurring_transactions(self):
        """Catch up all missed occurrences and keep occurrence dates accurate."""
        today = today_string()
        rows = self._execute("""
            SELECT id, type, category, amount, description, frequency, next_date
            FROM recurring_transactions
            WHERE active = 1 AND next_date <= ?
            ORDER BY next_date
        """, (today,)).fetchall()

        if not rows:
            return

        with self.conn:
            for rec in rows:
                next_date = rec["next_date"]
                occurrence_count = 0

                # Catch up every missed occurrence. This also guarantees that
                # next_date is moved into the future after a long absence.
                while next_date <= today:
                    self._execute("""
                        INSERT INTO transactions
                            (date, type, category, amount, description)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        next_date,
                        rec["type"],
                        rec["category"],
                        rec["amount"],
                        f"{rec['description']} (Auto)",
                    ))
                    next_date = calculate_next_date(rec["frequency"], next_date)
                    occurrence_count += 1

                    # Defensive guard against a malformed custom frequency.
                    if occurrence_count > 10000:
                        raise RuntimeError(
                            f"Recurring transaction {rec['id']} produced too many occurrences."
                        )

                self._execute(
                    "UPDATE recurring_transactions SET next_date = ? WHERE id = ?",
                    (next_date, rec["id"]),
                )

    def _calculate_next_date(self, frequency, current_date):
        return calculate_next_date(frequency, current_date)

    # ---------------- Settings ----------------

    def get_setting(self, key, default=None):
        row = self._execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        with self.conn:
            self._execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))

    # ---------------- Transactions ----------------

    def add_transaction(self, date, type_, category, amount, description):
        date, type_, category, amount, description = validate_transaction_values(
            date, type_, category, amount, description
        )
        with self.conn:
            self._execute("""
                INSERT INTO transactions (date, type, category, amount, description)
                VALUES (?, ?, ?, ?, ?)
            """, (date, type_, category, amount, description))

    def add_transactions(self, transactions):
        """Bulk insert used by CSV import so large imports commit once."""
        prepared = []
        for transaction in transactions:
            prepared.append(validate_transaction_values(*transaction))

        with self.conn:
            self.conn.executemany("""
                INSERT INTO transactions (date, type, category, amount, description)
                VALUES (?, ?, ?, ?, ?)
            """, prepared)

    def add_recurring_transaction(
        self, type_, category, amount, description, frequency, start_date
    ):
        start_date = parse_date(start_date, "Start date")
        type_ = type_.strip().lower()
        if type_ not in TRANSACTION_TYPES:
            raise ValueError("Transaction type must be income or expense.")
        category = category.strip()
        if not category:
            raise ValueError("Please enter a category.")
        amount = parse_positive_amount(str(amount))
        if frequency not in FREQUENCIES:
            raise ValueError("Invalid recurring frequency.")

        # Preserve original behavior: start_date is the date from which the
        # first occurrence is scheduled, rather than an immediate transaction.
        next_date = self._calculate_next_date(frequency, start_date)
        with self.conn:
            self._execute("""
                INSERT INTO recurring_transactions
                    (type, category, amount, description, frequency, next_date, active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (type_, category, amount, description.strip(), frequency, next_date))

    def get_all_transactions(self):
        return self._execute(
            "SELECT * FROM transactions ORDER BY date DESC, id DESC"
        ).fetchall()

    def get_filtered_transactions(
        self, search_term="", category="", type_="", date_start="", date_end=""
    ):
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []

        if search_term:
            query += " AND (description LIKE ? OR category LIKE ?)"
            params.extend([f"%{search_term}%", f"%{search_term}%"])
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

        query += " ORDER BY date DESC, id DESC"
        return self._execute(query, params).fetchall()

    def get_summary(self):
        return self._execute(
            "SELECT type, SUM(amount) AS total FROM transactions GROUP BY type"
        ).fetchall()

    def get_expenses_by_category(self):
        return self._execute("""
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE type = 'expense'
            GROUP BY category
            ORDER BY SUM(amount) DESC
        """).fetchall()

    def get_balance_over_time(self, days=30):
        """Return actual running balance, including transactions before the window."""
        days = max(1, int(days))
        opening_row = self._execute("""
            SELECT COALESCE(SUM(
                CASE WHEN type = 'income' THEN amount ELSE -amount END
            ), 0) AS balance
            FROM transactions
            WHERE date < date('now', ?)
        """, (f"-{days} days",)).fetchone()
        running_balance = float(opening_row["balance"] or 0)

        daily_data = self._execute("""
            SELECT date,
                   SUM(CASE WHEN type='income' THEN amount ELSE -amount END) AS daily_change
            FROM transactions
            WHERE date >= date('now', ?)
            GROUP BY date
            ORDER BY date
        """, (f"-{days} days",)).fetchall()

        result = []
        for row in daily_data:
            running_balance += float(row["daily_change"] or 0)
            result.append((row["date"], running_balance))
        return result

    def get_all_categories(self):
        rows = self._execute(
            "SELECT DISTINCT category FROM transactions ORDER BY category"
        ).fetchall()
        return [row["category"] for row in rows]

    def get_recurring_transactions(self):
        return self._execute(
            "SELECT * FROM recurring_transactions WHERE active = 1 ORDER BY next_date"
        ).fetchall()

    def delete_recurring_transaction(self, transaction_id):
        with self.conn:
            self._execute(
                "UPDATE recurring_transactions SET active = 0 WHERE id = ?",
                (transaction_id,),
            )

    def delete_transaction(self, transaction_id):
        with self.conn:
            self._execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    def update_transaction(self, transaction_id, date, type_, category, amount, description):
        date, type_, category, amount, description = validate_transaction_values(
            date, type_, category, amount, description
        )
        with self.conn:
            self._execute("""
                UPDATE transactions
                SET date = ?, type = ?, category = ?, amount = ?, description = ?
                WHERE id = ?
            """, (date, type_, category, amount, description, transaction_id))

    def get_transaction_by_id(self, transaction_id):
        return self._execute(
            "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()

    # ---------------- Budgets ----------------

    def add_budget(self, category, monthly_limit):
        category = category.strip()
        if not category:
            raise ValueError("Please enter a category.")
        monthly_limit = parse_positive_amount(str(monthly_limit), "Budget")
        month_year = datetime.now().strftime("%Y-%m")

        with self.conn:
            self._execute("""
                INSERT INTO budgets (category, monthly_limit, month_year)
                VALUES (?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET
                    monthly_limit = excluded.monthly_limit,
                    month_year = excluded.month_year
            """, (category, monthly_limit, month_year))

    def get_budgets(self):
        return self._execute("SELECT * FROM budgets ORDER BY category").fetchall()

    def delete_budget(self, budget_id):
        with self.conn:
            self._execute("DELETE FROM budgets WHERE id = ?", (budget_id,))

    def get_budget_usage(self, category):
        month_year = datetime.now().strftime("%Y-%m")
        budget_row = self._execute("""
            SELECT monthly_limit
            FROM budgets
            WHERE category = ? AND month_year = ?
        """, (category, month_year)).fetchone()

        if not budget_row:
            return None, None

        spent_row = self._execute("""
            SELECT COALESCE(SUM(amount), 0) AS spent
            FROM transactions
            WHERE category = ?
              AND type = 'expense'
              AND strftime('%Y-%m', date) = ?
        """, (category, month_year)).fetchone()
        return float(spent_row["spent"] or 0), float(budget_row["monthly_limit"])

    def get_all_budget_usage(self):
        """Fetch all current budget usage in one query instead of N+1 queries."""
        month_year = datetime.now().strftime("%Y-%m")
        return self._execute("""
            SELECT b.id, b.category, b.monthly_limit,
                   COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b
            LEFT JOIN transactions t
              ON t.category = b.category
             AND t.type = 'expense'
             AND strftime('%Y-%m', t.date) = ?
            WHERE b.month_year = ?
            GROUP BY b.id, b.category, b.monthly_limit
            ORDER BY b.category
        """, (month_year, month_year)).fetchall()

    def check_budget_warning(self, category, amount):
        spent, limit = self.get_budget_usage(category)
        if limit is None:
            return None

        new_total = spent + float(amount)
        percentage = (new_total / limit) * 100
        if percentage > 100:
            return "exceeded"
        if percentage > 80:
            return "warning"
        return None

    # ---------------- Import / Export / Backup ----------------

    def export_to_csv(self, filename="finance_export.csv"):
        transactions = self.get_all_transactions()
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["ID", "Date", "Type", "Category", "Amount", "Description"])
            for row in transactions:
                writer.writerow(tuple(row))
        return filename

    def import_from_csv(self, filename):
        success = 0
        errors = 0
        prepared = []

        try:
            with open(filename, mode="r", newline="", encoding="utf-8-sig") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    try:
                        date = row.get("Date", "").strip()
                        type_ = row.get("Type", "").strip().lower()
                        category = row.get("Category", "").strip()
                        amount_str = row.get("Amount", "").strip()
                        description = row.get("Description", "").strip()

                        if not all((date, type_, category, amount_str)):
                            raise ValueError("Missing required field")
                        if type_ not in TRANSACTION_TYPES:
                            raise ValueError("Invalid transaction type")

                        amount = parse_positive_amount(amount_str)
                        date = parse_date(date)
                        prepared.append((date, type_, category, amount, description))
                        success += 1
                    except (ValueError, TypeError, AttributeError):
                        errors += 1

            # One transaction for the entire import.
            self.add_transactions(prepared)
        except OSError as exc:
            raise Exception(f"Failed to read file: {exc}") from exc

        return success, errors

    def backup_database(self, backup_path):
        """Use SQLite's backup API so the resulting database is consistent."""
        destination = sqlite3.connect(backup_path)
        try:
            with destination:
                self.conn.backup(destination)
        finally:
            destination.close()
        return backup_path

    def restore_database(self, backup_path):
        """Validate, restore and reopen the database connection."""
        if os.path.abspath(backup_path) == os.path.abspath(self.db_name):
            raise ValueError("The backup file must be different from the active database.")

        # Validate the backup before replacing anything.
        source = sqlite3.connect(backup_path)
        try:
            result = source.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("The selected backup failed SQLite integrity_check.")
        finally:
            source.close()

        self.close()
        shutil.copy2(backup_path, self.db_name)
        self.conn = sqlite3.connect(self.db_name)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def close(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()
            self.conn = None


# ============================================================
# THEME
# ============================================================

class ThemeManager:
    LIGHT_THEME = {
        "bg": "#f0f0f0", "fg": "#000000", "card_bg": "#ffffff",
        "accent": "#2196F3", "entry_bg": "#ffffff", "button_bg": "#e1e1e1",
        "tree_bg": "#ffffff", "tree_fg": "#000000", "chart_bg": "#ffffff",
        "chart_fg": "#000000", "chart_grid": "#e0e0e0",
    }
    DARK_THEME = {
        "bg": "#2b2b2b", "fg": "#ffffff", "card_bg": "#3c3c3c",
        "accent": "#4fc3f7", "entry_bg": "#3c3c3c", "button_bg": "#4a4a4a",
        "tree_bg": "#3c3c3c", "tree_fg": "#ffffff", "chart_bg": "#2b2b2b",
        "chart_fg": "#ffffff", "chart_grid": "#555555",
    }

    def __init__(self, db):
        self.db = db
        self.current_theme = db.get_setting("theme", "light")

    def get_colors(self):
        return self.DARK_THEME if self.current_theme == "dark" else self.LIGHT_THEME

    def toggle_theme(self):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.db.set_setting("theme", self.current_theme)
        return self.current_theme

    def apply_to_matplotlib(self, fig, ax):
        colors = self.get_colors()
        fig.patch.set_facecolor(colors["chart_bg"])
        ax.set_facecolor(colors["chart_bg"])
        ax.tick_params(colors=colors["chart_fg"])
        ax.xaxis.label.set_color(colors["chart_fg"])
        ax.yaxis.label.set_color(colors["chart_fg"])
        ax.title.set_color(colors["chart_fg"])
        for spine in ax.spines.values():
            spine.set_edgecolor(colors["chart_grid"])
        for line in ax.xaxis.get_gridlines() + ax.yaxis.get_gridlines():
            line.set_color(colors["chart_grid"])


# ============================================================
# REUSABLE GUI HELPERS
# ============================================================

class FinanceCharts:
    """Shared chart rendering so dashboard and analytics don't duplicate logic."""

    def __init__(self, theme_manager):
        self.theme_manager = theme_manager

    def draw_expense_pie(self, fig, ax, canvas, expenses, title=None):
        ax.clear()
        if expenses:
            labels = [row[0] for row in expenses]
            values = [row[1] for row in expenses]
            ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
            ax.axis("equal")
            if title:
                ax.set_title(title)
        else:
            ax.text(0.5, 0.5, "No expense data available", ha="center", va="center")
            ax.axis("off")
        self.theme_manager.apply_to_matplotlib(fig, ax)
        canvas.draw_idle()

    def draw_balance_line(self, fig, ax, canvas, balance_data, title=None, mini=False):
        ax.clear()
        if balance_data:
            dates = [datetime.strptime(row[0], "%Y-%m-%d") for row in balance_data]
            balances = [row[1] for row in balance_data]
            ax.plot(dates, balances, marker="o", linewidth=2,
                    markersize=4 if mini else 5)
            if not mini:
                ax.fill_between(dates, balances, alpha=0.2)
                ax.set_ylabel("Balance ($)")
            ax.tick_params(axis="x", rotation=45)
            ax.grid(True, alpha=0.3)
            if title:
                ax.set_title(title)
            fig.autofmt_xdate()
        else:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center")
            ax.axis("off")
        self.theme_manager.apply_to_matplotlib(fig, ax)
        canvas.draw_idle()


class TransactionForm:
    """Reusable form builder used by the add and edit transaction dialogs."""

    def __init__(self, parent, values=None, include_title=True, start_row=0):
        self.parent = parent
        values = values or {}
        row = start_row

        if include_title:
            ttk.Label(parent, text="Transaction Details",
                      font=("Helvetica", 14, "bold")).grid(
                row=row, column=0, columnspan=2, pady=(0, 15)
            )
            row += 1

        self.date = self._field("Date (YYYY-MM-DD):", values.get("date", today_string()), row)
        row += 1
        self.type = self._combo("Type:", TRANSACTION_TYPES,
                                values.get("type", "expense"), row)
        row += 1
        self.category = self._field("Category:", values.get("category", ""), row)
        row += 1
        self.amount = self._field("Amount:", values.get("amount", ""), row)
        row += 1
        self.description = self._field("Description:", values.get("description", ""), row)

    def _field(self, label, value, row):
        ttk.Label(self.parent, text=label).grid(
            row=row, column=0, sticky="e", padx=5, pady=5
        )
        entry = ttk.Entry(self.parent, width=30)
        if value != "":
            entry.insert(0, str(value))
        entry.grid(row=row, column=1, padx=5, pady=5)
        return entry

    def _combo(self, label, values, current, row):
        ttk.Label(self.parent, text=label).grid(
            row=row, column=0, sticky="e", padx=5, pady=5
        )
        combo = ttk.Combobox(self.parent, values=values, state="readonly", width=28)
        combo.set(current)
        combo.grid(row=row, column=1, padx=5, pady=5)
        return combo

    def get_values(self):
        return {
            "date": self.date.get(),
            "type": self.type.get(),
            "category": self.category.get(),
            "amount": self.amount.get(),
            "description": self.description.get(),
        }

    def validate(self):
        values = self.get_values()
        return validate_transaction_values(
            values["date"], values["type"], values["category"],
            values["amount"], values["description"]
        )


# ============================================================
# APPLICATION / PRESENTATION LAYER
# ============================================================

class FinanceDesktopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("💰 Personal Finance Tracker Pro")
        self.root.geometry("1100x750")
        self.root.minsize(950, 700)

        self.db = FinanceDatabase()
        self.theme_manager = ThemeManager(self.db)
        self.charts = FinanceCharts(self.theme_manager)

        self.style = ttk.Style()
        self.style.theme_use("clam")

        self._apply_theme()
        self._build_ui()
        self._refresh_dashboard()
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ---------------- Theme ----------------

    def _apply_theme(self):
        colors = self.theme_manager.get_colors()
        self.root.configure(bg=colors["bg"])
        self.style.configure(".", background=colors["bg"], foreground=colors["fg"])
        self.style.configure("TFrame", background=colors["bg"])
        self.style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
        self.style.configure("TButton", background=colors["button_bg"], foreground=colors["fg"])
        self.style.configure("TEntry", fieldbackground=colors["entry_bg"], foreground=colors["fg"])
        self.style.configure("TCombobox", fieldbackground=colors["entry_bg"], foreground=colors["fg"])
        self.style.configure("TNotebook", background=colors["bg"])
        self.style.configure("TNotebook.Tab", background=colors["button_bg"],
                             foreground=colors["fg"], padding=[10, 5])
        self.style.configure("TLabelframe", background=colors["bg"], foreground=colors["fg"])
        self.style.configure("TLabelframe.Label", background=colors["bg"], foreground=colors["accent"])
        self.style.configure("Treeview", background=colors["tree_bg"],
                             foreground=colors["tree_fg"], fieldbackground=colors["tree_bg"])
        self.style.configure("Treeview.Heading", background=colors["button_bg"], foreground=colors["fg"])
        self.style.map("Treeview", background=[("selected", colors["accent"])])
        self.style.configure("Card.TFrame", background=colors["card_bg"])
        self.style.configure("Card.TLabel", background=colors["card_bg"], foreground=colors["fg"])
        self.style.configure("Accent.TButton", background=colors["accent"], foreground="white")
        self.style.map("Accent.TButton", background=[("active", colors["accent"])])

    def _toggle_theme(self):
        self.theme_manager.toggle_theme()
        self._apply_theme()
        self._update_theme_button_text()
        self._refresh_dashboard()
        if hasattr(self, "full_pie_canvas"):
            self._update_charts()

    def _update_theme_button_text(self):
        self.theme_btn.config(
            text="☀️ Light Mode" if self.theme_manager.current_theme == "dark" else "🌙 Dark Mode"
        )

    # ---------------- UI construction ----------------

    def _build_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=10, pady=5)
        ttk.Label(header, text="💰 Personal Finance Tracker Pro",
                  font=("Helvetica", 16, "bold")).pack(side="left", padx=10)
        self.theme_btn = ttk.Button(header, command=self._toggle_theme)
        self.theme_btn.pack(side="right", padx=10)
        self._update_theme_button_text()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_dashboard = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dashboard, text="📊 Dashboard")
        self._build_dashboard()

        self.tab_add = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_add, text="➕ Add Transaction")
        self._build_add_form()

        self.tab_recurring = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_recurring, text="🔁 Recurring")
        self._build_recurring_form()

        self.tab_budgets = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_budgets, text="🎯 Budgets")
        self._build_budgets_tab()

        self.tab_history = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_history, text="📜 History")
        self._build_history_table()

        self.tab_charts = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_charts, text="📈 Analytics")
        self._build_charts_tab()

        self.tab_data = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_data, text="💾 Data Management")
        self._build_data_tab()

    def _build_dashboard(self):
        main_frame = ttk.Frame(self.tab_dashboard)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        summary_frame = ttk.Frame(main_frame)
        summary_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(summary_frame, text="Financial Overview",
                  font=("Helvetica", 18, "bold")).pack(pady=(0, 15))

        cards_frame = ttk.Frame(summary_frame)
        cards_frame.pack(fill="x")
        self.lbl_income_title = ttk.Label(cards_frame, text="Total Income", font=("Helvetica", 12))
        self.lbl_income_title.grid(row=0, column=0, padx=20, pady=10)
        self.lbl_income_val = ttk.Label(cards_frame, text="$0.00", font=("Helvetica", 20, "bold"), foreground="green")
        self.lbl_income_val.grid(row=1, column=0, padx=20)
        self.lbl_expense_title = ttk.Label(cards_frame, text="Total Expenses", font=("Helvetica", 12))
        self.lbl_expense_title.grid(row=0, column=1, padx=20, pady=10)
        self.lbl_expense_val = ttk.Label(cards_frame, text="$0.00", font=("Helvetica", 20, "bold"), foreground="red")
        self.lbl_expense_val.grid(row=1, column=1, padx=20)
        self.lbl_balance_title = ttk.Label(cards_frame, text="Net Balance", font=("Helvetica", 12))
        self.lbl_balance_title.grid(row=0, column=2, padx=20, pady=10)
        self.lbl_balance_val = ttk.Label(cards_frame, text="$0.00", font=("Helvetica", 24, "bold"))
        self.lbl_balance_val.grid(row=1, column=2, padx=20)

        stats_frame = ttk.Frame(summary_frame)
        stats_frame.pack(fill="x", pady=10)
        self.lbl_total_transactions = ttk.Label(stats_frame, text="Total Transactions: 0")
        self.lbl_total_transactions.pack(side="left", padx=20)
        self.lbl_recurring_count = ttk.Label(stats_frame, text="Active Recurring: 0")
        self.lbl_recurring_count.pack(side="left", padx=20)

        self.budget_alerts_frame = ttk.LabelFrame(main_frame, text="⚠️ Budget Alerts", padding=10)
        self.budget_alerts_frame.pack(fill="x", pady=(0, 10))
        self.budget_alerts_label = ttk.Label(self.budget_alerts_frame, text="No budget alerts", foreground="gray")
        self.budget_alerts_label.pack()

        charts_container = ttk.Frame(main_frame)
        charts_container.pack(fill="both", expand=True)
        pie_frame = ttk.LabelFrame(charts_container, text="Expenses by Category", padding=10)
        pie_frame.pack(side="left", fill="both", expand=True, padx=5)
        self.pie_fig = Figure(figsize=(4, 3))
        self.pie_ax = self.pie_fig.add_subplot(111)
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_frame)
        self.pie_canvas.get_tk_widget().pack(fill="both", expand=True)

        line_frame = ttk.LabelFrame(charts_container, text="Balance Trend (30 days)", padding=10)
        line_frame.pack(side="right", fill="both", expand=True, padx=5)
        self.line_fig = Figure(figsize=(4, 3))
        self.line_ax = self.line_fig.add_subplot(111)
        self.line_canvas = FigureCanvasTkAgg(self.line_fig, master=line_frame)
        self.line_canvas.get_tk_widget().pack(fill="both", expand=True)
        ttk.Button(summary_frame, text="🔄 Refresh Dashboard",
                   command=self._refresh_dashboard).pack(pady=10)

    def _build_add_form(self):
        frame = ttk.Frame(self.tab_add, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Log a New Transaction",
                  font=("Helvetica", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))
        self.add_form = TransactionForm(frame, include_title=False, start_row=1)
        # The form starts at row 1.
        for child in frame.grid_slaves():
            info = child.grid_info()
            if int(info.get("row", 0)) == 0 and child is not self.add_form.parent:
                pass
        ttk.Button(frame, text="Add Transaction", command=self._submit_transaction).grid(
            row=6, column=0, columnspan=2, pady=20
        )

    def _build_recurring_form(self):
        frame = ttk.Frame(self.tab_recurring, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Set Up Recurring Transaction",
                  font=("Helvetica", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))

        self.rec_combo_type = self._make_combo(frame, "Type:", TRANSACTION_TYPES, "expense", 1)
        self.rec_entry_category = self._make_entry(frame, "Category:", 2)
        self.rec_entry_amount = self._make_entry(frame, "Amount:", 3)
        self.rec_entry_desc = self._make_entry(frame, "Description:", 4)
        self.rec_combo_frequency = self._make_combo(frame, "Frequency:", FREQUENCIES, "monthly", 5)
        self.rec_entry_start_date = self._make_entry(frame, "Start Date:", 6, today_string())

        ttk.Button(frame, text="Add Recurring Transaction",
                   command=self._submit_recurring_transaction).grid(row=7, column=0, columnspan=2, pady=20)
        ttk.Separator(frame, orient="horizontal").grid(row=8, column=0, columnspan=2, sticky="ew", pady=20)
        ttk.Label(frame, text="Active Recurring Transactions",
                  font=("Helvetica", 14, "bold")).grid(row=9, column=0, columnspan=2, pady=(0, 10))

        self.rec_tree = ttk.Treeview(frame,
            columns=("id", "type", "category", "amount", "frequency", "next_date"),
            show="headings", height=6)
        for column, title, width, anchor in [
            ("id", "ID", 40, "center"), ("type", "Type", 80, "center"),
            ("category", "Category", 120, "w"), ("amount", "Amount", 100, "e"),
            ("frequency", "Frequency", 100, "center"), ("next_date", "Next Date", 100, "center")]:
            self.rec_tree.heading(column, text=title)
            self.rec_tree.column(column, width=width, anchor=anchor)
        self.rec_tree.grid(row=10, column=0, columnspan=2, pady=10, sticky="nsew")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=11, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="🗑️ Delete Selected", command=self._delete_recurring_selected).pack(side="right")
        ttk.Button(btn_frame, text="🔄 Refresh", command=self._refresh_recurring_list).pack(side="right", padx=10)
        frame.grid_rowconfigure(10, weight=1)

    def _make_entry(self, parent, label, row, value=""):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=5)
        entry = ttk.Entry(parent, width=30)
        if value:
            entry.insert(0, value)
        entry.grid(row=row, column=1, padx=5, pady=5)
        return entry

    def _make_combo(self, parent, label, values, current, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=5)
        combo = ttk.Combobox(parent, values=values, state="readonly", width=28)
        combo.set(current)
        combo.grid(row=row, column=1, padx=5, pady=5)
        return combo

    def _build_budgets_tab(self):
        frame = ttk.Frame(self.tab_budgets, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="🎯 Budget Management", font=("Helvetica", 16, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 20)
        )
        form_frame = ttk.LabelFrame(frame, text="Set Monthly Budget", padding=15)
        form_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        self.budget_entry_category = self._make_entry(form_frame, "Category:", 0)
        self.budget_entry_limit = self._make_entry(form_frame, "Monthly Limit ($):", 1)
        ttk.Button(form_frame, text="💾 Save Budget", command=self._save_budget).grid(row=2, column=0, columnspan=2, pady=15)

        ttk.Label(frame, text="Your Budgets", font=("Helvetica", 14, "bold")).grid(
            row=2, column=0, columnspan=2, pady=(20, 10)
        )
        self.budgets_container = ttk.Frame(frame)
        self.budgets_container.grid(row=3, column=0, columnspan=2, sticky="nsew")
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="🗑️ Delete Selected", command=self._delete_budget_selected).pack(side="right")
        ttk.Button(btn_frame, text="🔄 Refresh", command=self._refresh_budgets_list).pack(side="right", padx=10)
        frame.grid_rowconfigure(3, weight=1)
        frame.grid_columnconfigure(1, weight=1)
        self._refresh_budgets_list()

    def _build_history_table(self):
        frame = ttk.Frame(self.tab_history, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Transaction History", font=("Helvetica", 16, "bold")).pack(pady=(0, 10))
        filter_frame = ttk.LabelFrame(frame, text="Search & Filter", padding=10)
        filter_frame.pack(fill="x", pady=(0, 10))
        search_frame = ttk.Frame(filter_frame)
        search_frame.pack(fill="x", pady=5)
        ttk.Label(search_frame, text="Search:").pack(side="left", padx=5)
        self.search_entry = ttk.Entry(search_frame, width=30)
        self.search_entry.pack(side="left", padx=5)
        self.search_entry.bind("<KeyRelease>", lambda _: self._apply_filters())
        ttk.Label(search_frame, text="Type:").pack(side="left", padx=(20, 5))
        self.filter_type = ttk.Combobox(search_frame, values=["", *TRANSACTION_TYPES], state="readonly", width=15)
        self.filter_type.pack(side="left", padx=5)
        self.filter_type.bind("<<ComboboxSelected>>", lambda _: self._apply_filters())

        date_frame = ttk.Frame(filter_frame)
        date_frame.pack(fill="x", pady=5)
        ttk.Label(date_frame, text="Category:").pack(side="left", padx=5)
        self.filter_category = ttk.Combobox(date_frame, values=[""], state="readonly", width=20)
        self.filter_category.pack(side="left", padx=5)
        self.filter_category.bind("<<ComboboxSelected>>", lambda _: self._apply_filters())
        ttk.Label(date_frame, text="From:").pack(side="left", padx=(20, 5))
        self.filter_date_start = ttk.Entry(date_frame, width=12)
        self.filter_date_start.pack(side="left", padx=5)
        self.filter_date_start.insert(0, current_month_start())
        self.filter_date_start.bind("<KeyRelease>", lambda _: self._apply_filters())
        ttk.Label(date_frame, text="To:").pack(side="left", padx=(10, 5))
        self.filter_date_end = ttk.Entry(date_frame, width=12)
        self.filter_date_end.pack(side="left", padx=5)
        self.filter_date_end.insert(0, today_string())
        self.filter_date_end.bind("<KeyRelease>", lambda _: self._apply_filters())
        ttk.Button(date_frame, text="Clear Filters", command=self._clear_filters).pack(side="left", padx=20)

        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame,
            columns=("row", "date", "type", "category", "amount", "description"), show="headings")
        for column, title, width, anchor in [
            ("row", "#", 40, "center"), ("date", "Date", 100, "center"),
            ("type", "Type", 80, "center"), ("category", "Category", 120, "w"),
            ("amount", "Amount", 100, "e"), ("description", "Description", 300, "w")]:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor)
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side="bottom", fill="x", pady=10)
        ttk.Button(btn_frame, text="🔄 Refresh", command=self._refresh_history).pack(side="left", padx=5)
        right_btns = ttk.Frame(btn_frame)
        right_btns.pack(side="right")
        ttk.Button(right_btns, text="✏️ Edit Selected", command=self._edit_selected).pack(side="left", padx=5)
        ttk.Button(right_btns, text="🗑️ Delete Selected", command=self._delete_selected).pack(side="left", padx=5)
        self._refresh_history()

    def _build_charts_tab(self):
        frame = ttk.Frame(self.tab_charts, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Financial Analytics", font=("Helvetica", 18, "bold")).pack(pady=(0, 10))
        control_frame = ttk.Frame(frame)
        control_frame.pack(fill="x", pady=10)
        ttk.Label(control_frame, text="Show balance for last:").pack(side="left", padx=5)
        self.days_var = tk.StringVar(value="30")
        days_combo = ttk.Combobox(control_frame, textvariable=self.days_var,
                                   values=["7", "30", "90", "365"], width=10, state="readonly")
        days_combo.pack(side="left", padx=5)
        days_combo.bind("<<ComboboxSelected>>", lambda _: self._update_charts())
        ttk.Button(control_frame, text="🔄 Update Charts", command=self._update_charts).pack(side="left", padx=20)

        charts_frame = ttk.Frame(frame)
        charts_frame.pack(fill="both", expand=True)
        pie_frame = ttk.LabelFrame(charts_frame, text="Expense Breakdown by Category", padding=10)
        pie_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.full_pie_fig = Figure(figsize=(6, 5))
        self.full_pie_ax = self.full_pie_fig.add_subplot(111)
        self.full_pie_canvas = FigureCanvasTkAgg(self.full_pie_fig, master=pie_frame)
        self.full_pie_canvas.get_tk_widget().pack(fill="both", expand=True)

        line_frame = ttk.LabelFrame(charts_frame, text="Balance Over Time", padding=10)
        line_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        self.full_line_fig = Figure(figsize=(6, 5))
        self.full_line_ax = self.full_line_fig.add_subplot(111)
        self.full_line_canvas = FigureCanvasTkAgg(self.full_line_fig, master=line_frame)
        self.full_line_canvas.get_tk_widget().pack(fill="both", expand=True)
        self._update_charts()

    def _build_data_tab(self):
        frame = ttk.Frame(self.tab_data, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="💾 Data Management", font=("Helvetica", 18, "bold")).pack(pady=(0, 20))
        export_frame = ttk.LabelFrame(frame, text="Export Data", padding=15)
        export_frame.pack(fill="x", pady=10)
        ttk.Label(export_frame, text="Export your transactions to a CSV file for use in Excel or Google Sheets.",
                  wraplength=600, justify="left").pack(pady=5)
        ttk.Button(export_frame, text="📤 Export to CSV", command=self._export_data).pack(pady=10)
        import_frame = ttk.LabelFrame(frame, text="Import Data", padding=15)
        import_frame.pack(fill="x", pady=10)
        ttk.Label(import_frame, text="Import transactions from a CSV file. The file should have columns: Date, Type, Category, Amount, Description",
                  wraplength=600, justify="left").pack(pady=5)
        ttk.Button(import_frame, text="📥 Import from CSV", command=self._import_data).pack(pady=10)
        backup_frame = ttk.LabelFrame(frame, text="Database Backup & Restore", padding=15)
        backup_frame.pack(fill="x", pady=10)
        ttk.Label(backup_frame, text="Create a complete backup of your database or restore from a previous backup.",
                  wraplength=600, justify="left").pack(pady=5)
        btn_row = ttk.Frame(backup_frame)
        btn_row.pack(pady=10)
        ttk.Button(btn_row, text="💾 Create Backup", command=self._create_backup).pack(side="left", padx=10)
        ttk.Button(btn_row, text="📂 Restore from Backup", command=self._restore_backup).pack(side="left", padx=10)
        ttk.Label(backup_frame, text="⚠️ Warning: Restoring will overwrite all current data!",
                  foreground="red").pack(pady=5)

    # ---------------- Dashboard ----------------

    def _refresh_dashboard(self):
        summary = self.db.get_summary()
        totals = {row["type"]: float(row["total"] or 0) for row in summary}
        income = totals.get("income", 0.0)
        expense = totals.get("expense", 0.0)
        balance = income - expense

        self.lbl_income_val.config(text=f"${income:,.2f}")
        self.lbl_expense_val.config(text=f"${expense:,.2f}")
        self.lbl_balance_val.config(text=f"${balance:,.2f}", foreground="green" if balance >= 0 else "red")
        self.lbl_total_transactions.config(
            text=f"Total Transactions: {len(self.db.get_all_transactions())}"
        )
        self.lbl_recurring_count.config(
            text=f"Active Recurring: {len(self.db.get_recurring_transactions())}"
        )
        self._update_budget_alerts()
        self._update_mini_charts()
        self.filter_category["values"] = [""] + self.db.get_all_categories()

    def _update_budget_alerts(self):
        alerts = []
        for row in self.db.get_all_budget_usage():
            category = row["category"]
            spent = float(row["spent"] or 0)
            limit = float(row["monthly_limit"])
            percentage = (spent / limit) * 100 if limit else 0
            if percentage > 100:
                alerts.append(f"🔴 {category}: OVER BUDGET (${spent:.2f} / ${limit:.2f})")
            elif percentage > 80:
                alerts.append(f"🟡 {category}: Approaching limit (${spent:.2f} / ${limit:.2f})")

        for widget in self.budget_alerts_frame.winfo_children():
            widget.destroy()
        if not alerts:
            ttk.Label(self.budget_alerts_frame, text="✅ All budgets on track!", foreground="green").pack()
        else:
            for alert in alerts:
                ttk.Label(self.budget_alerts_frame, text=alert).pack(anchor="w", pady=2)

    def _update_mini_charts(self):
        self.charts.draw_expense_pie(
            self.pie_fig, self.pie_ax, self.pie_canvas,
            self.db.get_expenses_by_category()
        )
        self.charts.draw_balance_line(
            self.line_fig, self.line_ax, self.line_canvas,
            self.db.get_balance_over_time(30), mini=True
        )

    def _update_charts(self):
        days = int(self.days_var.get())
        self.charts.draw_expense_pie(
            self.full_pie_fig, self.full_pie_ax, self.full_pie_canvas,
            self.db.get_expenses_by_category(), title="Total Expenses by Category"
        )
        self.charts.draw_balance_line(
            self.full_line_fig, self.full_line_ax, self.full_line_canvas,
            self.db.get_balance_over_time(days), title=f"Balance Trend (Last {days} Days)"
        )

    # ---------------- History ----------------

    def _apply_filters(self):
        transactions = self.db.get_filtered_transactions(
            search_term=self.search_entry.get(),
            category=self.filter_category.get(),
            type_=self.filter_type.get(),
            date_start=self.filter_date_start.get(),
            date_end=self.filter_date_end.get(),
        )
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, row in enumerate(transactions, start=1):
            self.tree.insert("", tk.END, iid=str(row["id"]), values=(
                i, row["date"], row["type"], row["category"],
                f"${row['amount']:,.2f}", row["description"]
            ))

    def _clear_filters(self):
        self.search_entry.delete(0, tk.END)
        self.filter_type.set("")
        self.filter_category.set("")
        self.filter_date_start.delete(0, tk.END)
        self.filter_date_start.insert(0, current_month_start())
        self.filter_date_end.delete(0, tk.END)
        self.filter_date_end.insert(0, today_string())
        self._refresh_history()

    def _refresh_history(self):
        self._apply_filters()

    # ---------------- Recurring / budgets ----------------

    def _refresh_recurring_list(self):
        for item in self.rec_tree.get_children():
            self.rec_tree.delete(item)
        for row in self.db.get_recurring_transactions():
            self.rec_tree.insert("", tk.END, values=(
                row["id"], row["type"], row["category"],
                f"${row['amount']:,.2f}", row["frequency"], row["next_date"]
            ))

    def _refresh_budgets_list(self):
        for widget in self.budgets_container.winfo_children():
            widget.destroy()
        budgets = self.db.get_all_budget_usage()
        if not budgets:
            ttk.Label(self.budgets_container, text="No budgets set yet. Add one above!",
                      foreground="gray").pack(pady=20)
            return

        tree = ttk.Treeview(self.budgets_container,
            columns=("id", "category", "limit", "spent", "remaining", "progress"), show="headings", height=8)
        for column, title, width, anchor in [
            ("id", "ID", 40, "center"), ("category", "Category", 120, "w"),
            ("limit", "Monthly Limit", 100, "e"), ("spent", "Spent This Month", 100, "e"),
            ("remaining", "Remaining", 100, "e"), ("progress", "Status", 150, "center")]:
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor=anchor)
        tree.pack(fill="both", expand=True, pady=10)
        self.budget_tree = tree

        for budget in budgets:
            budget_id = budget["id"]
            category = budget["category"]
            limit = float(budget["monthly_limit"])
            spent = float(budget["spent"] or 0)
            remaining = limit - spent
            percentage = (spent / limit) * 100 if limit else 0
            if percentage > 100:
                status = f"🔴 OVER ({percentage:.0f}%)"
            elif percentage > 80:
                status = f"🟡 Warning ({percentage:.0f}%)"
            else:
                status = f"🟢 OK ({percentage:.0f}%)"
            tree.insert("", tk.END, iid=str(budget_id), values=(
                budget_id, category, f"${limit:,.2f}", f"${spent:,.2f}",
                f"${remaining:,.2f}", status
            ))

    def _submit_transaction(self):
        values = self.add_form.get_values()
        try:
            date, type_, category, amount, description = self.add_form.validate()
        except ValueError as exc:
            messagebox.showerror("Input Error", str(exc))
            return

        if type_ == "expense":
            warning = self.db.check_budget_warning(category, amount)
            if warning == "exceeded":
                if not messagebox.askyesno(
                    "⚠️ Budget Exceeded",
                    f"Adding this expense will EXCEED your budget for '{category}'.\n\nContinue anyway?"
                ):
                    return
            elif warning == "warning":
                messagebox.showinfo(
                    "💡 Budget Notice",
                    f"Warning: This expense will bring you close to your budget limit for '{category}'."
                )

        try:
            self.db.add_transaction(date, type_, category, amount, description)
        except ValueError as exc:
            messagebox.showerror("Input Error", str(exc))
            return

        self.add_form.category.delete(0, tk.END)
        self.add_form.amount.delete(0, tk.END)
        self.add_form.description.delete(0, tk.END)
        self.add_form.date.delete(0, tk.END)
        self.add_form.date.insert(0, today_string())
        self._refresh_all()
        messagebox.showinfo("Success", "Transaction added successfully!")
        self.notebook.select(self.tab_dashboard)

    def _submit_recurring_transaction(self):
        type_ = self.rec_combo_type.get()
        category = self.rec_entry_category.get().strip()
        amount = self.rec_entry_amount.get()
        description = self.rec_entry_desc.get().strip()
        frequency = self.rec_combo_frequency.get()
        start_date = self.rec_entry_start_date.get()
        try:
            self.db.add_recurring_transaction(type_, category, amount, description, frequency, start_date)
        except ValueError as exc:
            messagebox.showerror("Input Error", str(exc))
            return
        self.rec_entry_category.delete(0, tk.END)
        self.rec_entry_amount.delete(0, tk.END)
        self.rec_entry_desc.delete(0, tk.END)
        self._refresh_recurring_list()
        self._refresh_dashboard()
        messagebox.showinfo("Success", f"Recurring {frequency} transaction added!")

    def _delete_recurring_selected(self):
        selected_items = self.rec_tree.selection()
        if not selected_items:
            messagebox.showwarning("Selection Error", "Please select a recurring transaction to delete.")
            return
        transaction_id = self.rec_tree.item(selected_items[0], "values")[0]
        if messagebox.askyesno("Confirm Deletion", "Delete this recurring transaction?"):
            self.db.delete_recurring_transaction(transaction_id)
            self._refresh_recurring_list()
            self._refresh_dashboard()
            messagebox.showinfo("Success", "Recurring transaction deleted!")

    # ---------------- Transaction edit/delete ----------------

    def _delete_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Selection Error", "Please select a transaction to delete.")
            return
        transaction_id = selected_items[0]
        item_values = self.tree.item(transaction_id, "values")
        transaction_desc = item_values[5]
        if messagebox.askyesno("Confirm Deletion", f"Delete this transaction?\n\nDesc: {transaction_desc}"):
            self.db.delete_transaction(transaction_id)
            self._refresh_all()
            messagebox.showinfo("Success", "Transaction deleted!")

    def _edit_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Selection Error", "Please select a transaction to edit.")
            return
        transaction_id = selected_items[0]
        db_row = self.db.get_transaction_by_id(transaction_id)
        if not db_row:
            messagebox.showerror("Error", "Transaction not found.")
            return

        edit_window = tk.Toplevel(self.root)
        edit_window.title("Edit Transaction")
        edit_window.geometry("400x350")
        edit_window.resizable(False, False)
        edit_window.grab_set()
        frame = ttk.Frame(edit_window, padding=20)
        frame.pack(fill="both", expand=True)
        form = TransactionForm(frame, values={
            "date": db_row["date"], "type": db_row["type"],
            "category": db_row["category"], "amount": db_row["amount"],
            "description": db_row["description"],
        }, start_row=1)

        def save_changes():
            try:
                date, type_, category, amount, description = form.validate()
                self.db.update_transaction(
                    transaction_id, date, type_, category, amount, description
                )
            except ValueError as exc:
                messagebox.showerror("Input Error", str(exc), parent=edit_window)
                return
            self._refresh_all()
            edit_window.destroy()
            messagebox.showinfo("Success", "Transaction updated!")

        ttk.Button(frame, text="💾 Save Changes", command=save_changes).grid(
            row=6, column=0, columnspan=2, pady=20
        )

    # ---------------- Budgets ----------------

    def _save_budget(self):
        category = self.budget_entry_category.get().strip()
        limit_str = self.budget_entry_limit.get().strip()
        try:
            limit = parse_positive_amount(limit_str, "Budget")
            self.db.add_budget(category, limit)
        except ValueError as exc:
            messagebox.showerror("Input Error", str(exc))
            return
        self.budget_entry_category.delete(0, tk.END)
        self.budget_entry_limit.delete(0, tk.END)
        self._refresh_budgets_list()
        self._refresh_dashboard()
        messagebox.showinfo("Success", f"Budget set for '{category}': ${limit:,.2f}/month")

    def _delete_budget_selected(self):
        if not hasattr(self, "budget_tree"):
            return
        selected = self.budget_tree.selection()
        if not selected:
            messagebox.showwarning("Selection Error", "Please select a budget to delete.")
            return
        budget_id = selected[0]
        category = self.budget_tree.item(budget_id, "values")[1]
        if messagebox.askyesno("Confirm Deletion", f"Delete budget for '{category}'?"):
            self.db.delete_budget(budget_id)
            self._refresh_budgets_list()
            self._refresh_dashboard()
            messagebox.showinfo("Success", "Budget deleted!")

    # ---------------- Data management ----------------

    def _export_data(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"finance_export_{datetime.now().strftime('%Y%m%d')}.csv"
        )
        if not filename:
            return
        try:
            self.db.export_to_csv(filename)
            messagebox.showinfo("Export Successful", f"Data exported to:\n{filename}")
        except Exception as exc:
            messagebox.showerror("Export Error", f"An error occurred: {exc}")

    def _import_data(self):
        filename = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not filename or not messagebox.askyesno(
            "Confirm Import",
            "This will import transactions from the CSV file.\n\nContinue?"
        ):
            return
        try:
            success, errors = self.db.import_from_csv(filename)
            self._refresh_all()
            messagebox.showinfo(
                "Import Complete",
                f"Import successful!\n\n✅ Imported: {success} transactions\n❌ Skipped: {errors} rows"
            )
        except Exception as exc:
            messagebox.showerror("Import Error", f"An error occurred: {exc}")

    def _create_backup(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("Database files", "*.db"), ("All files", "*.*")],
            initialfile=f"finance_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        if not filename:
            return
        try:
            self.db.backup_database(filename)
            messagebox.showinfo("Backup Created", f"Backup saved to:\n{filename}")
        except Exception as exc:
            messagebox.showerror("Backup Error", f"An error occurred: {exc}")

    def _restore_backup(self):
        filename = filedialog.askopenfilename(
            filetypes=[("Database files", "*.db"), ("All files", "*.*")]
        )
        if not filename:
            return
        if not messagebox.askyesno(
            "⚠️ Confirm Restore",
            "WARNING: This will REPLACE all current data with the backup!\n\n"
            "This action cannot be undone.\n\nContinue?"
        ):
            return
        try:
            self.db.restore_database(filename)
            messagebox.showinfo("Restore Successful", "Database restored! The app will now refresh.")
            self._refresh_all()
            self._refresh_recurring_list()
            self._refresh_budgets_list()
        except Exception as exc:
            messagebox.showerror("Restore Error", f"An error occurred: {exc}")

    # ---------------- Refresh / lifecycle ----------------

    def _refresh_all(self):
        self._refresh_dashboard()
        self._refresh_history()
        self._refresh_recurring_list()
        self._refresh_budgets_list()
        if hasattr(self, "full_pie_canvas"):
            self._update_charts()

    def _on_closing(self):
        self.db.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = FinanceDesktopApp(root)
    root.mainloop()
