from datetime import date
from decimal import Decimal

import pytest
from app.domain.account import Account
from app.domain.date_range import DateRange
from app.domain.money import Money
from app.domain.recurrence import calculate_next_date
from app.domain.transaction import Transaction
from app.schemas import AccountCreate, RecurringCreate, RecurringUpdate, TransactionCreate
from pydantic import ValidationError


def test_money_rounds_half_up_normalizes_currency_and_subtracts():
    amount = Money.from_amount("1.005", " usd ")

    assert amount.cents == 101
    assert amount.currency == "USD"
    assert amount.amount == Decimal("1.01")
    assert (amount - Money(1, "USD")).cents == 100


@pytest.mark.parametrize("currency", ["", "US", "US1", "EURO"])
def test_money_rejects_invalid_currency_codes(currency):
    with pytest.raises(ValueError, match="three-letter"):
        Money(100, currency)


def test_account_rejects_blank_name_and_mixed_currency_balances():
    values = {
        "id": 1,
        "name": "Checking",
        "type": "checking",
        "currency": "USD",
        "opening_balance": Money(0, "USD"),
        "balance": Money(0, "USD"),
        "active": True,
        "created_at": "2026-08-29T00:00:00+00:00",
        "transaction_count": 0,
    }

    with pytest.raises(ValueError, match="name"):
        Account(**{**values, "name": "   "})
    with pytest.raises(ValueError, match="account currency"):
        Account(**{**values, "balance": Money(0, "EUR")})


def test_transaction_rejects_invalid_type_and_blank_category():
    values = {
        "id": 1,
        "date": date.today(),
        "type": "expense",
        "category": "Food",
        "amount": Money(100, "USD"),
        "description": "Lunch",
        "account_id": 1,
        "account_name": "Checking",
    }

    with pytest.raises(ValueError, match="type"):
        Transaction(**{**values, "type": "transfer"})
    with pytest.raises(ValueError, match="category"):
        Transaction(**{**values, "category": "   "})


def test_date_range_serializes_optional_boundaries():
    assert DateRange().start_iso == ""
    assert DateRange().end_iso == ""
    assert DateRange(start=date(2026, 8, 1)).start_iso == "2026-08-01"
    assert DateRange(end=date(2026, 8, 31)).end_iso == "2026-08-31"


def test_recurrence_rejects_unknown_frequency_and_handles_regular_year():
    assert calculate_next_date("yearly", date(2025, 3, 1)) == date(2026, 3, 1)
    with pytest.raises(ValueError, match="Unsupported frequency"):
        calculate_next_date("fortnightly", date.today())


def test_request_schemas_trim_and_normalize_text_fields():
    transaction = TransactionCreate(date=date.today(), type="expense", category="  Food  ", amount="10.00")
    recurring = RecurringCreate(
        type="expense",
        category="  Rent  ",
        amount="500.00",
        frequency="monthly",
        start_date=date.today(),
    )
    recurring_update = RecurringUpdate(
        type="expense",
        category="  Utilities  ",
        amount="50.00",
        frequency="monthly",
        next_date=date.today(),
    )
    account = AccountCreate(name="  Savings  ", currency=" eur ")

    assert transaction.category == "Food"
    assert recurring.category == "Rent"
    assert recurring_update.category == "Utilities"
    assert account.name == "Savings"
    assert account.currency == "EUR"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            TransactionCreate,
            {"date": date.today(), "type": "expense", "category": "   ", "amount": 1},
        ),
        (
            RecurringCreate,
            {
                "type": "expense",
                "category": "   ",
                "amount": 1,
                "frequency": "daily",
                "start_date": date.today(),
            },
        ),
        (
            RecurringUpdate,
            {
                "type": "expense",
                "category": "   ",
                "amount": 1,
                "frequency": "daily",
                "next_date": date.today(),
            },
        ),
        (AccountCreate, {"name": "   "}),
        (AccountCreate, {"name": "Savings", "currency": "12$"}),
    ],
)
def test_request_schemas_reject_invalid_normalized_text(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)
