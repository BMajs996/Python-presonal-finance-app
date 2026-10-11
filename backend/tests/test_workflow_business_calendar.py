from datetime import date, datetime

import pytest
from app.core.config import settings
from app.domain import business_date
from app.repositories.reconciliation_repository import ReconciliationRepository
from app.services.finance_service import FinanceService
from app.services.reconciliation_service import ReconciliationService

from . import test_postgres as postgres_cases
from . import test_reconciliation as reconciliation_cases
from . import test_service_workflows as workflow_cases
from .postgres_helpers import pg_url as pg_url
from .test_postgres import pg_repo as pg_repo


@pytest.fixture(params=["2026-01-31T23:30:00+00:00", "2026-09-30T22:30:00+00:00"])
def ci_calendar(request, monkeypatch):
    instant = datetime.fromisoformat(request.param)
    monkeypatch.setattr(settings, "business_timezone", "Europe/Belgrade")
    monkeypatch.setattr(business_date, "utc_now", lambda: instant)

    class ServerDate(date):
        @classmethod
        def today(cls):
            return instant.date()

    # Model CI's UTC calendar without changing the real machine clock or timezone.
    for module in (workflow_cases, reconciliation_cases, postgres_cases):
        monkeypatch.setattr(module, "date", ServerDate, raising=False)
    assert ServerDate.today() < business_date.today()


@pytest.mark.parametrize("backend", ["db", "pg_repo"])
@pytest.mark.parametrize("case", ["recurring", "reconciliation", "budgets"])
def test_workflows_when_ci_and_business_dates_differ(ci_calendar, request, backend, case):
    repository = request.getfixturevalue(backend)
    if case == "recurring":
        workflow_cases.test_finance_service_account_transfer_and_recurring_workflows(
            FinanceService(repository)
        )
    elif case == "budgets":
        workflow_cases.test_finance_service_transaction_and_budget_workflows(FinanceService(repository))
    else:
        service = ReconciliationService(ReconciliationRepository(repository.conn))
        reconciliation_cases.test_dates_duplicate_drafts_and_inactive_accounts(repository, service)


def test_concurrent_recurring_when_ci_and_business_dates_differ(ci_calendar, pg_repo):
    postgres_cases.test_concurrent_recurring_and_restore(pg_repo)
