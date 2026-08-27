from datetime import date, timedelta

import pytest
from app.domain.account import Account
from app.domain.money import Money
from app.domain.transaction import Transaction
from app.schemas import AccountCreate, TransactionCreate, TransferCreate
from pydantic import ValidationError


def test_money_uses_exact_integer_cents():
    first = Money.from_amount("0.10", "USD")
    second = Money.from_amount("0.20", "USD")

    assert (first + second).cents == 30
    assert (first + second).as_float() == 0.30


def test_money_rejects_cross_currency_arithmetic():
    with pytest.raises(ValueError, match="different currencies"):
        Money(100, "USD") + Money(100, "EUR")


def test_transaction_and_account_domain_objects_enforce_invariants():
    balance = Money(10_000, "USD")
    account = Account(
        id=1,
        name="Checking",
        type="checking",
        currency="USD",
        opening_balance=balance,
        balance=balance,
        active=True,
        created_at="2026-08-27T00:00:00+00:00",
        transaction_count=0,
    )
    transaction = Transaction(
        id=1,
        date=date.today(),
        type="expense",
        category="Food",
        amount=Money(1299, "USD"),
        description="Lunch",
        account_id=account.id,
        account_name=account.name,
    )

    assert account.to_dict()["balance"] == 100
    assert transaction.to_dict()["amount"] == 12.99
    with pytest.raises(ValueError, match="positive"):
        Transaction(
            id=2,
            date=date.today(),
            type="expense",
            category="Food",
            amount=Money(0, "USD"),
            description="",
            account_id=account.id,
            account_name=account.name,
        )


def test_repository_persists_exact_cents(db):
    transaction = db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount="10.29",
        )
    )

    stored = db.database.conn.execute(
        "SELECT amount_cents FROM transactions WHERE id=?",
        (transaction["id"],),
    ).fetchone()
    assert stored["amount_cents"] == 1029
    assert transaction["amount"] == 10.29


def test_income_minus_expenses_always_equals_net(db, finance_service):
    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Salary",
            amount="1000.10",
        )
    )
    db.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="expense",
            category="Food",
            amount="200.03",
        )
    )

    dashboard = finance_service.dashboard()
    assert Money.from_amount(dashboard["income"] - dashboard["expenses"]).cents == (
        Money.from_amount(dashboard["net"]).cents
    )
    assert dashboard["net"] == 800.07


def test_transfer_is_neutral_to_global_and_monthly_balance(db, finance_service):
    checking = db.add_account(
        AccountCreate(name="Checking", opening_balance="1000.00")
    )
    savings = db.add_account(AccountCreate(name="Savings", type="savings"))
    before = finance_service.monthly_report(months=3)

    db.add_transfer(
        TransferCreate(
            date=date.today(),
            from_account_id=checking["id"],
            to_account_id=savings["id"],
            amount="333.33",
        )
    )
    after = finance_service.monthly_report(months=3)

    assert before["months"][-1]["balance"] == after["months"][-1]["balance"] == 1000
    assert finance_service.dashboard()["balance"] == 1000
    account_total = sum(account["balance"] for account in db.list_accounts())
    assert account_total == 1000


def test_base_currency_prevents_implicit_fx(db):
    with pytest.raises(ValueError, match="base currency"):
        db.add_account(AccountCreate(name="Euro account", currency="EUR"))


def test_new_database_uses_configured_base_currency(tmp_path):
    from app.database import FinanceDatabase
    from app.repositories.finance_repository import FinanceRepository

    database = FinanceDatabase(tmp_path / "euro.db", base_currency="EUR")
    repository = FinanceRepository(database, base_currency="EUR")
    try:
        assert repository.list_accounts()[0]["currency"] == "EUR"
        account = repository.add_account(AccountCreate(name="Savings", currency="EUR"))
        assert account["currency"] == "EUR"
    finally:
        repository.close()


def test_date_validation_rejects_malformed_and_reversed_ranges(finance_service):
    with pytest.raises(ValidationError):
        TransactionCreate(
            date="not-a-date",
            type="expense",
            category="Food",
            amount="10.00",
        )

    with pytest.raises(ValueError, match="Start date"):
        finance_service.list_transactions(
            date_start=date.today(),
            date_end=date.today() - timedelta(days=1),
        )
