from datetime import date

import pytest
from app.domain.recurrence import add_months, calculate_next_date


def test_add_months_handles_end_of_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)


def test_add_months_handles_year_boundary():
    assert add_months(date(2026, 12, 31), 1) == date(2027, 1, 31)


def test_recurring_date_calculations():
    assert calculate_next_date("daily", date(2026, 8, 1)) == date(2026, 8, 2)
    assert calculate_next_date("weekly", date(2026, 8, 1)) == date(2026, 8, 8)
    assert calculate_next_date("monthly", date(2026, 1, 31)) == date(2026, 2, 28)
    assert calculate_next_date("yearly", date(2024, 2, 29)) == date(2025, 2, 28)


def test_add_and_read_transaction(db):
    from app.schemas import TransactionCreate

    transaction = db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 23),
            type="income",
            category="Salary",
            amount=2500,
            description="Monthly salary",
        )
    )

    assert transaction["id"] > 0
    assert transaction["category"] == "Salary"
    assert transaction["amount"] == 2500

    rows, total = db.list_transactions()
    assert total == 1
    assert rows[0]["description"] == "Monthly salary"


def test_update_transaction(db):
    from app.schemas import TransactionCreate

    created = db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 23),
            type="expense",
            category="Food",
            amount=20,
            description="Lunch",
        )
    )

    updated = db.update_transaction(
        created["id"],
        TransactionCreate(
            date=date(2026, 8, 23),
            type="expense",
            category="Groceries",
            amount=50,
            description="Weekly groceries",
        ),
    )

    assert updated["category"] == "Groceries"
    assert updated["amount"] == 50
    assert updated["description"] == "Weekly groceries"


def test_delete_transaction(db):
    from app.schemas import TransactionCreate

    created = db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 23),
            type="expense",
            category="Food",
            amount=20,
            description="Lunch",
        )
    )

    db.delete_transaction(created["id"])

    assert db.get_transaction(created["id"]) is None
    assert db.list_transactions()[1] == 0


def test_dashboard_calculates_balance_income_expenses_and_net(db, finance_service):
    from app.schemas import TransactionCreate

    db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 20),
            type="income",
            category="Salary",
            amount=3000,
        )
    )
    db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 21),
            type="expense",
            category="Food",
            amount=100,
        )
    )
    db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 22),
            type="expense",
            category="Transport",
            amount=200,
        )
    )

    dashboard = finance_service.dashboard(days=30)

    assert dashboard["balance"] == 2700
    assert dashboard["income"] == 3000
    assert dashboard["expenses"] == 300
    assert dashboard["net"] == 2700
    assert {x["category"] for x in dashboard["expense_categories"]} == {
        "Food",
        "Transport",
    }


def test_transaction_filters(db):
    from app.schemas import TransactionCreate

    db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 20),
            type="expense",
            category="Food",
            amount=20,
            description="Restaurant",
        )
    )
    db.add_transaction(
        TransactionCreate(
            date=date(2026, 8, 21),
            type="income",
            category="Salary",
            amount=2000,
            description="Salary",
        )
    )

    rows, total = db.list_transactions(category="Food")
    assert total == 1
    assert rows[0]["description"] == "Restaurant"

    rows, total = db.list_transactions(type_="income")
    assert total == 1
    assert rows[0]["category"] == "Salary"

    rows, total = db.list_transactions(search="rest")
    assert total == 1


def test_budget_usage(db):
    from app.schemas import BudgetCreate, TransactionCreate

    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount=250,
        )
    )

    budget = db.add_budget(BudgetCreate(category="Food", monthly_limit=500))

    assert budget["category"] == "Food"
    assert budget["spent"] == 250
    assert budget["percentage"] == 50


def test_budget_upsert_does_not_duplicate_category(db):
    from app.schemas import BudgetCreate

    first = db.add_budget(BudgetCreate(category="Food", monthly_limit=500))
    second = db.add_budget(BudgetCreate(category="Food", monthly_limit=700))

    assert second["id"] == first["id"]
    assert second["monthly_limit"] == 700
    assert len(db.get_budget_usage()) == 1


def test_update_budget(db):
    from app.schemas import BudgetCreate

    created = db.add_budget(BudgetCreate(category="Food", monthly_limit=500))
    updated = db.update_budget(
        created["id"],
        BudgetCreate(category="Groceries", monthly_limit=650),
    )

    assert updated["id"] == created["id"]
    assert updated["category"] == "Groceries"
    assert updated["monthly_limit"] == 650


def test_recurring_transaction_catches_up_missed_occurrences(db):
    from app.schemas import RecurringCreate

    recurring = db.add_recurring(
        RecurringCreate(
            type="expense",
            category="Rent",
            amount=800,
            description="Rent",
            frequency="monthly",
            start_date=date(2026, 1, 1),
        )
    )

    assert recurring["active"] == 1

    assert recurring["next_date"] == "2026-02-01"

    db.recurring_transactions.process_due(through=date(2026, 4, 1))

    transactions, total = db.list_transactions()
    assert total == 3
    assert {row["date"] for row in transactions} == {
        "2026-02-01",
        "2026-03-01",
        "2026-04-01",
    }
    assert db.recurring()[0]["next_date"] == "2026-05-01"


def test_update_recurring_transaction(db):
    from app.schemas import RecurringCreate, RecurringUpdate

    recurring = db.add_recurring(
        RecurringCreate(
            type="expense",
            category="Rent",
            amount=800,
            description="Rent",
            frequency="monthly",
            start_date=date(2026, 1, 1),
        )
    )
    updated = db.update_recurring(
        recurring["id"],
        RecurringUpdate(
            type="income",
            category="Salary",
            amount=3000,
            description="Monthly salary",
            frequency="monthly",
            next_date=date(2026, 2, 15),
        ),
    )

    assert updated["id"] == recurring["id"]
    assert updated["type"] == "income"
    assert updated["category"] == "Salary"
    assert updated["next_date"] == "2026-02-15"


def test_monthly_report(db, finance_service):
    from app.schemas import TransactionCreate

    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Salary",
            amount=3000,
        )
    )
    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount=600,
        )
    )

    report = finance_service.monthly_report(months=3)

    assert len(report["months"]) == 3
    assert report["summary"]["income"] == 3000
    assert report["summary"]["expenses"] == 600
    assert report["summary"]["savings_rate"] == 80
    assert report["top_categories"][0] == {"category": "Food", "total": 600}
    assert report["category_trends"][0]["category"] == "Food"
    assert report["category_trends"][0]["totals"][-1] == 600


def test_categories_are_unique(db):
    from app.schemas import TransactionCreate

    for amount in (10, 20):
        db.add_transaction(
            TransactionCreate(
                date=date.today(),
                type="expense",
                category="Food",
                amount=amount,
            )
        )

    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Transport",
            amount=30,
        )
    )

    assert db.categories() == ["Food", "Transport"]


def test_legacy_database_is_migrated_without_changing_balance(tmp_path):
    import sqlite3

    from app.database import FinanceDatabase
    from app.repositories.finance_repository import FinanceRepository

    legacy_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    conn.executescript(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            type TEXT,
            category TEXT,
            amount REAL,
            description TEXT
        );
        CREATE TABLE recurring_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            category TEXT,
            amount REAL,
            description TEXT,
            frequency TEXT,
            next_date TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE,
            monthly_limit REAL,
            month_year TEXT
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO transactions(date, type, category, amount, description)
        VALUES ('2026-08-20', 'income', 'Salary', 1000, 'Legacy salary');
        INSERT INTO transactions(date, type, category, amount, description)
        VALUES ('2026-08-21', 'expense', 'Food', 100, 'Legacy food');
        """
    )
    conn.commit()
    conn.close()

    database = FinanceDatabase(legacy_path)
    repository = FinanceRepository(database)
    try:
        assert database.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
        assert database.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert (
            database.conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE account_id IS NOT NULL"
            ).fetchone()[0]
            == 2
        )
        assert database.conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0] == 110000
        from app.services.finance_service import FinanceService

        assert FinanceService(repository).dashboard()["balance"] == 900
    finally:
        database.close()


def test_accounts_and_balances(db):
    from app.schemas import AccountCreate, TransactionCreate

    savings = db.add_account(AccountCreate(name="Savings", type="savings", opening_balance=1000))
    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Interest",
            amount=25,
            account_id=savings["id"],
        )
    )
    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount=75,
            account_id=savings["id"],
        )
    )

    account = db.get_account(savings["id"])
    assert account["balance"] == 950
    assert account["transaction_count"] == 2


def test_transfers_move_money_without_changing_global_net(db, finance_service):
    from app.schemas import AccountCreate, TransferCreate

    checking = db.add_account(AccountCreate(name="Checking"))
    savings = db.add_account(AccountCreate(name="Savings", type="savings"))

    transfer = db.add_transfer(
        TransferCreate(
            date=date.today(),
            from_account_id=checking["id"],
            to_account_id=savings["id"],
            amount=500,
            description="Move to savings",
        )
    )

    assert transfer["amount"] == 500
    assert db.get_account(checking["id"])["balance"] == -500
    assert db.get_account(savings["id"])["balance"] == 500
    assert finance_service.dashboard()["net"] == 0
    assert finance_service.dashboard()["balance"] == 0


def test_transaction_defaults_to_main_account(db):
    from app.schemas import TransactionCreate

    transaction = db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Salary",
            amount=100,
        )
    )

    assert transaction["account_name"] == "Main Account"
    assert transaction["account_id"] is not None


def test_transfer_cannot_use_same_account(db):
    from app.schemas import TransferCreate

    main_id = db.accounts.default_account_id()
    with pytest.raises(ValueError, match="different"):
        db.add_transfer(
            TransferCreate(
                date=date.today(),
                from_account_id=main_id,
                to_account_id=main_id,
                amount=100,
            )
        )
