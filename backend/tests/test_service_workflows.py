from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from app.migrations import migrate
from app.repositories.base_repository import BaseRepository
from app.schemas import (
    AccountCreate,
    BudgetCreate,
    RecurringCreate,
    RecurringUpdate,
    TransactionCreate,
    TransferCreate,
)


def test_finance_service_transaction_and_budget_workflows(finance_service):
    transaction = finance_service.create_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount="12.50",
            description="Lunch",
        )
    )

    assert finance_service.get_transaction(transaction["id"])["amount"] == 12.5
    rows, total = finance_service.list_transactions(category="Food")
    assert total == 1
    assert rows[0]["id"] == transaction["id"]
    assert finance_service.categories() == ["Food"]

    updated = finance_service.update_transaction(
        transaction["id"],
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Groceries",
            amount="20.00",
        ),
    )
    assert updated["category"] == "Groceries"
    finance_service.delete_transaction(transaction["id"])
    assert finance_service.get_transaction(transaction["id"]) is None

    budget = finance_service.create_budget(BudgetCreate(category="Groceries", monthly_limit="300.00"))
    assert finance_service.budgets()[0]["id"] == budget["id"]
    updated_budget = finance_service.update_budget(
        budget["id"], BudgetCreate(category="Food", monthly_limit="350.00")
    )
    assert updated_budget["monthly_limit"] == 350
    finance_service.delete_budget(budget["id"])
    assert finance_service.budgets() == []


def test_finance_service_account_transfer_and_recurring_workflows(finance_service):
    checking = finance_service.create_account(AccountCreate(name="Checking"))
    savings = finance_service.create_account(AccountCreate(name="Savings", type="savings"))

    assert finance_service.get_account(checking["id"])["name"] == "Checking"
    assert {account["name"] for account in finance_service.accounts()} >= {
        "Checking",
        "Savings",
    }

    transfer = finance_service.create_transfer(
        TransferCreate(
            date=date.today(),
            from_account_id=checking["id"],
            to_account_id=savings["id"],
            amount="25.00",
        )
    )
    assert finance_service.get_transfer(transfer["id"])["amount"] == 25
    assert finance_service.transfers(limit=10)[0]["id"] == transfer["id"]
    finance_service.delete_transfer(transfer["id"])
    assert finance_service.get_transfer(transfer["id"]) is None

    recurring = finance_service.create_recurring(
        RecurringCreate(
            type="income",
            category="Allowance",
            amount="10.00",
            frequency="daily",
            start_date=date.today() - timedelta(days=1),
            account_id=checking["id"],
        )
    )
    assert finance_service.recurring()[0]["id"] == recurring["id"]
    updated = finance_service.update_recurring(
        recurring["id"],
        RecurringUpdate(
            type="income",
            category="Allowance",
            amount="15.00",
            frequency="daily",
            next_date=date.today(),
            account_id=checking["id"],
        ),
    )
    assert updated["amount"] == 15
    finance_service.recurring_service.process_due()
    assert finance_service.list_transactions(category="Allowance")[1] == 1
    finance_service.delete_recurring(recurring["id"])
    assert finance_service.recurring() == []

    finance_service.deactivate_account(savings["id"])
    assert finance_service.get_account(savings["id"])["active"] == 0


def test_repository_missing_record_and_account_failure_paths(db):
    from app.schemas import RecurringUpdate

    assert db.get_account(99999) is None
    assert db.get_transaction(99999) is None
    assert db.get_transfer(99999) is None
    assert (
        db.update_transaction(
            99999,
            TransactionCreate(date=date.today(), type="expense", category="Food", amount=1),
        )
        is None
    )
    assert db.update_budget(99999, BudgetCreate(category="Food", monthly_limit=1)) is None
    assert (
        db.update_recurring(
            99999,
            RecurringUpdate(
                type="expense",
                category="Rent",
                amount=1,
                frequency="monthly",
                next_date=date.today(),
            ),
        )
        is None
    )

    main_account_id = db.accounts.default_account_id()
    with pytest.raises(ValueError, match="cannot be deactivated"):
        db.deactivate_account(main_account_id)
    with pytest.raises(ValueError, match="does not exist or is inactive"):
        db.accounts.resolve_account_id(99999)
    with pytest.raises(ValueError, match="does not exist"):
        db.accounts.account_currency(99999)


def test_migration_is_idempotent_and_insert_id_requires_a_value(db):
    assert migrate(db.database.conn, db.base_currency) == 2
    assert migrate(db.database.conn, db.base_currency) == 2

    with pytest.raises(RuntimeError, match="did not return an id"):
        BaseRepository.inserted_id(SimpleNamespace(lastrowid=None))
