from datetime import UTC, date, datetime, time, timedelta

import pytest
from app.domain import business_date
from app.domain.date_range import DateRange
from app.domain.errors import InvalidOperation

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


@pytest.fixture
def today(monkeypatch):
    fixed = date(2026, 9, 27)

    monkeypatch.setattr(business_date, "utc_now", lambda: datetime.combine(fixed, time(12), UTC))
    return fixed


@pytest.mark.parametrize("days", [1, 7, 30, 365])
def test_chart_and_summary_share_inclusive_boundaries(raw_client, today, days):
    login_client(raw_client)
    start = today - timedelta(days=days - 1)
    response = raw_client.post("/api/accounts", json={"name": "Opening balance", "opening_balance": "100.10"})
    assert response.status_code == 201
    account = response.json()["id"]

    def add(day, kind, amount):
        if day > today:
            # Legacy future rows bypass the posted-only service, never the live database.
            from app.main import app
            from app.repositories.transaction_repository import TransactionRepository
            from app.schemas import TransactionCreate

            with app.state.database.connection() as conn:
                return TransactionRepository(conn).add(
                    TransactionCreate(
                        date=day,
                        type=kind,
                        category="Boundary",
                        amount=amount,
                        account_id=account,
                    )
                )["id"]
        response = raw_client.post(
            "/api/transactions",
            json={
                "date": day.isoformat(),
                "type": kind,
                "category": "Boundary",
                "amount": amount,
                "account_id": account,
            },
        )
        assert response.status_code == 201
        return response.json()["id"]

    add(start - timedelta(days=1), "income", "10.11")
    add(start - timedelta(days=1), "expense", "2.03")
    add(start, "income", "20.22")
    add(start, "expense", "3.04")
    add(today, "income", "5.06")
    add(today + timedelta(days=1), "income", "999.99")
    add(today + timedelta(days=1), "expense", "888.88")
    deleted = add(start, "expense", "777.77")
    assert raw_client.delete(f"/api/transactions/{deleted}").status_code == 204

    response = raw_client.get("/api/dashboard", params={"days": days})
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["period"] == {"days": days, "start": start.isoformat(), "end": today.isoformat()}
    assert dashboard["income"] == 25.28
    assert dashboard["expenses"] == 3.04
    assert dashboard["net"] == 22.24
    assert dashboard["expense_categories"] == [{"category": "Boundary", "total": 3.04}]
    expected = [
        {
            "date": (start + timedelta(days=offset)).isoformat(),
            "balance": 130.42 if offset == days - 1 else 125.36,
        }
        for offset in range(days)
    ]
    assert dashboard["balance_history"] == expected


@pytest.mark.parametrize("days", [1, 7, 30, 365])
def test_quiet_days_carry_opening_balance_through_today(raw_client, today, days):
    login_client(raw_client)
    start = today - timedelta(days=days - 1)
    response = raw_client.post(
        "/api/transactions",
        json={
            "date": (start - timedelta(days=1)).isoformat(),
            "type": "income",
            "category": "Opening",
            "amount": "12.34",
        },
    )
    assert response.status_code == 201
    dashboard = raw_client.get("/api/dashboard", params={"days": days}).json()
    assert dashboard["income"] == 0
    assert dashboard["expenses"] == 0
    assert dashboard["balance_history"] == [
        {"date": (start + timedelta(days=offset)).isoformat(), "balance": 12.34} for offset in range(days)
    ]
    assert dashboard["balance_history"][-1]["date"] == today.isoformat()


@pytest.mark.parametrize("days", [1, 7, 30, 365])
def test_empty_ledger_still_has_daily_closing_balances(raw_client, today, days):
    login_client(raw_client)
    dashboard = raw_client.get("/api/dashboard", params={"days": days}).json()
    history = dashboard["balance_history"]
    assert len(history) == days
    assert history[0]["date"] == dashboard["period"]["start"]
    assert history[-1]["date"] == dashboard["period"]["end"] == today.isoformat()
    assert all(point["balance"] == 0 for point in history)


def test_dashboard_reads_today_once_even_if_midnight_passes(raw_client, monkeypatch):
    login_client(raw_client)
    reads = []

    def moving_clock():
        value = date(2026, 9, 27) + timedelta(days=len(reads))
        reads.append(value)
        return datetime.combine(value, time(12), UTC)

    monkeypatch.setattr(business_date, "utc_now", moving_clock)
    dashboard = raw_client.get("/api/dashboard", params={"days": 7}).json()
    assert reads == [date(2026, 9, 27)]
    assert dashboard["period"] == {"days": 7, "start": "2026-09-21", "end": "2026-09-27"}
    assert dashboard["balance_history"][0]["date"] == "2026-09-21"
    assert dashboard["balance_history"][-1]["date"] == "2026-09-27"


@pytest.mark.parametrize(
    "end,start,days",
    [
        (date(2024, 3, 1), date(2024, 2, 28), 3),
        (date(2026, 1, 1), date(2025, 12, 31), 2),
        (date(2026, 1, 1), date(2026, 1, 1), 1),
    ],
)
def test_trailing_range_is_inclusive_across_calendar_boundaries(end, start, days):
    period = DateRange.trailing(days, end=end)
    assert period.start == start
    assert period.end == end
    assert period.days == days


@pytest.mark.parametrize("days", [0, -1])
def test_trailing_range_requires_positive_days(days):
    with pytest.raises(InvalidOperation, match="at least one day"):
        DateRange.trailing(days)


def test_trailing_range_rejects_calendar_underflow():
    with pytest.raises(InvalidOperation, match="supported date range"):
        DateRange.trailing(2, end=date.min)


def test_open_ended_filter_range_has_no_inclusive_day_count():
    with pytest.raises(InvalidOperation, match="both start and end"):
        _ = DateRange(start=date(2026, 9, 27)).days
