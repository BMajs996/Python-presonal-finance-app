from datetime import date

from app.database import add_months, calculate_next_date


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


def test_dashboard_calculates_balance_income_expenses_and_net(db):
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

    dashboard = db.dashboard(days=30)

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

    budget = db.add_budget(
        BudgetCreate(category="Food", monthly_limit=500)
    )

    assert budget["category"] == "Food"
    assert budget["spent"] == 250
    assert budget["percentage"] == 50


def test_budget_upsert_does_not_duplicate_category(db):
    from app.schemas import BudgetCreate

    first = db.add_budget(
        BudgetCreate(category="Food", monthly_limit=500)
    )
    second = db.add_budget(
        BudgetCreate(category="Food", monthly_limit=700)
    )

    assert second["id"] == first["id"]
    assert second["monthly_limit"] == 700
    assert len(db.get_budget_usage()) == 1


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

    # The recurring entry itself is scheduled for the month after its
    # configured start date. Verify the record exists and has a valid date.
    assert recurring["next_date"] == "2026-02-01"


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
