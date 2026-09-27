from datetime import date
from decimal import Decimal

import pytest
from app.domain.errors import InvalidOperation
from app.domain.money import MAX_AMOUNT, MAX_AMOUNT_CENTS, Money
from app.main import app
from app.schemas import RecurringCreate

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


@pytest.mark.parametrize(
    "value",
    ["NaN", "sNaN", "Infinity", "-Infinity", "1e100000", "invalid", "1000000000.01", "-1000000000.01"],
)
def test_domain_rejects_nonfinite_and_oversized_money(value):
    with pytest.raises(InvalidOperation):
        Money.from_amount(value)


def test_entry_limits_do_not_limit_aggregate_money():
    entry = Money.from_amount(MAX_AMOUNT)
    assert entry.cents == MAX_AMOUNT_CENTS
    assert (entry + entry).amount == Decimal("2000000000.00")
    assert Money.from_amount(-MAX_AMOUNT).cents == -MAX_AMOUNT_CENTS


@pytest.mark.parametrize("amount", ["1000000000.01", "1e100000", "NaN", "Infinity"])
def test_api_money_limits_are_controlled_validation_errors(raw_client, amount):
    login_client(raw_client)
    payloads = [
        (
            "/api/transactions",
            {"date": "2026-01-01", "type": "income", "category": "Salary", "amount": amount},
        ),
        ("/api/accounts", {"name": "Large", "opening_balance": amount}),
        ("/api/budgets", {"category": "Food", "monthly_limit": amount}),
        (
            "/api/transfers",
            {"date": "2026-01-01", "from_account_id": 1, "to_account_id": 2, "amount": amount},
        ),
        (
            "/api/recurring",
            {
                "type": "expense",
                "category": "Rent",
                "amount": amount,
                "frequency": "monthly",
                "start_date": "2026-01-01",
            },
        ),
    ]
    for path, payload in payloads:
        response = raw_client.post(path, json=payload)
        assert response.status_code == 422, (path, response.text)


def test_reports_preserve_totals_above_per_entry_limit(raw_client):
    login_client(raw_client)
    for _ in range(2):
        response = raw_client.post(
            "/api/transactions",
            json={
                "date": date.today().isoformat(),
                "type": "income",
                "category": "Large",
                "amount": str(MAX_AMOUNT),
            },
        )
        assert response.status_code == 201, response.text
    response = raw_client.get("/api/reports/monthly")
    assert response.status_code == 200
    assert response.json()["summary"]["income"] == 2000000000
    with app.state.database.connection() as conn:
        assert (
            conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()[0] == 2 * MAX_AMOUNT_CENTS
        )


@pytest.mark.parametrize("start", ["0001-01-01", "9999-12-31"])
def test_recurring_start_dates_have_supported_bounds(start):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RecurringCreate(type="income", category="Test", amount="1", frequency="daily", start_date=start)


def test_statement_balance_can_exceed_an_individual_entry_limit(raw_client):
    login_client(raw_client)
    account = raw_client.get("/api/accounts").json()[0]["id"]
    response = raw_client.post(
        "/api/reconciliations",
        json={
            "account_id": account,
            "closing_date": "2020-01-31",
            "closing_balance": "2000000000.01",
        },
    )
    assert response.status_code == 201
    assert response.json()["closing_balance_cents"] == 200000000001
