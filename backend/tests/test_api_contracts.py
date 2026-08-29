from datetime import date
from types import SimpleNamespace

import pytest
from app.api import accounts as accounts_api
from app.api import budgets as budgets_api
from app.api import recurring as recurring_api
from app.api import transactions as transactions_api
from app.api import transfers as transfers_api
from app.api.dependencies import get_finance_service
from app.core.config import Settings
from app.schemas import (
    BudgetCreate,
    RecurringUpdate,
    TransactionCreate,
    TransferCreate,
)
from fastapi import HTTPException
from pydantic import ValidationError


def test_settings_normalize_currency_and_parse_cors_origins():
    settings = Settings(
        base_currency=" eur ",
        cors_origins="http://localhost:8000, http://127.0.0.1:8000,",
        _env_file=None,
    )

    assert settings.base_currency == "EUR"
    assert settings.cors_origin_list == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    with pytest.raises(ValidationError, match="three-letter ISO"):
        Settings(base_currency="US1", _env_file=None)


def test_finance_service_dependency_reads_application_state(finance_service):
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(finance_service=finance_service)))

    assert get_finance_service(request) is finance_service


def test_transaction_handlers_map_invalid_ranges_and_missing_records(finance_service):
    with pytest.raises(HTTPException) as invalid_range:
        transactions_api.list_transactions(
            service=finance_service,
            search="",
            category="",
            type_="",
            account_id=None,
            date_start=date(2026, 8, 31),
            date_end=date(2026, 8, 1),
            limit=100,
            offset=0,
        )
    assert invalid_range.value.status_code == 400

    payload = TransactionCreate(date=date.today(), type="expense", category="Food", amount=10)
    with pytest.raises(HTTPException) as missing_update:
        transactions_api.update_transaction(99999, payload, finance_service)
    assert missing_update.value.status_code == 404

    with pytest.raises(HTTPException) as missing_delete:
        transactions_api.delete_transaction(99999, finance_service)
    assert missing_delete.value.status_code == 404


def test_account_and_transfer_handlers_map_domain_errors(finance_service):
    main_account_id = finance_service.accounts()[0]["id"]

    with pytest.raises(HTTPException) as main_account:
        accounts_api.deactivate_account(main_account_id, finance_service)
    assert main_account.value.status_code == 400

    with pytest.raises(HTTPException) as missing_account:
        accounts_api.deactivate_account(99999, finance_service)
    assert missing_account.value.status_code == 404

    transfer = TransferCreate(
        date=date.today(),
        from_account_id=main_account_id,
        to_account_id=main_account_id,
        amount=10,
    )
    with pytest.raises(HTTPException) as invalid_transfer:
        transfers_api.create_transfer(transfer, finance_service)
    assert invalid_transfer.value.status_code == 400

    with pytest.raises(HTTPException) as missing_transfer:
        transfers_api.delete_transfer(99999, finance_service)
    assert missing_transfer.value.status_code == 404


def test_budget_and_recurring_handlers_map_missing_records(finance_service):
    with pytest.raises(HTTPException) as missing_budget:
        budgets_api.update_budget(
            99999,
            BudgetCreate(category="Food", monthly_limit=100),
            finance_service,
        )
    assert missing_budget.value.status_code == 404

    with pytest.raises(HTTPException) as missing_recurring:
        recurring_api.update_recurring(
            99999,
            RecurringUpdate(
                type="expense",
                category="Rent",
                amount=100,
                frequency="monthly",
                next_date=date.today(),
            ),
            finance_service,
        )
    assert missing_recurring.value.status_code == 404
