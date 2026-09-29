import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from app.core.config import Settings, settings
from app.domain import business_date
from app.main import app
from app.services.recurring_runner import process_recurring
from pydantic import ValidationError

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


@pytest.fixture(autouse=True)
def belgrade(monkeypatch):
    monkeypatch.setattr(settings, "business_timezone", "Europe/Belgrade")


@pytest.mark.parametrize("name", ["", "Not/AZone", "/etc/passwd", "../UTC", "+02:00"])
def test_invalid_timezone_fails_configuration(name):
    with pytest.raises(ValidationError, match="BUSINESS_TIMEZONE"):
        Settings(business_timezone=name, _env_file=None)


@pytest.mark.parametrize("name", ["Europe/Belgrade", "UTC", "America/Los_Angeles"])
def test_valid_timezone_configuration(name):
    assert Settings(business_timezone=name, _env_file=None).business_timezone == name


@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-01-31T22:59:59+00:00", "2026-01-31"),
        ("2026-01-31T23:00:00+00:00", "2026-02-01"),
        ("2026-09-30T21:59:59+00:00", "2026-09-30"),
        ("2026-09-30T22:00:00+00:00", "2026-10-01"),
        ("2026-03-29T00:59:59+00:00", "2026-03-29"),
        ("2026-03-29T01:00:00+00:00", "2026-03-29"),
        ("2026-10-25T00:59:59+00:00", "2026-10-25"),
        ("2026-10-25T01:00:00+00:00", "2026-10-25"),
    ],
)
def test_utc_instants_map_to_business_calendar(instant, expected):
    with business_date.snapshot(lambda: datetime.fromisoformat(instant)):
        assert business_date.today().isoformat() == expected


def test_snapshot_freezes_and_resets_after_exception(monkeypatch):
    values = iter([datetime(2026, 9, 30, 21, 59, 59, tzinfo=UTC), datetime(2026, 9, 30, 22, tzinfo=UTC)])
    monkeypatch.setattr(business_date, "utc_now", lambda: next(values))
    with pytest.raises(RuntimeError):
        with business_date.snapshot():
            assert business_date.today() == date(2026, 9, 30)
            with business_date.snapshot():
                assert business_date.today() == date(2026, 9, 30)
            raise RuntimeError("test cleanup")
    assert business_date.today() == date(2026, 10, 1)


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        with business_date.snapshot(lambda: datetime(2026, 9, 30)):
            pass


def test_concurrent_snapshots_do_not_leak():
    async def read(day):
        with business_date.snapshot(lambda: datetime(2026, 9, day, 12, tzinfo=UTC)):
            await asyncio.sleep(0)
            return business_date.today()

    async def run():
        return await asyncio.gather(read(10), read(11))

    assert asyncio.run(run()) == [date(2026, 9, 10), date(2026, 9, 11)]


@pytest.mark.parametrize(
    "boundary",
    [
        "2026-01-31T23:00:00+00:00",
        "2026-09-30T22:00:00+00:00",
    ],
)
def test_month_boundary_changes_all_financial_rules(raw_client, monkeypatch, boundary):
    end = datetime.fromisoformat(boundary)
    instant = [end - timedelta(seconds=1)]
    monkeypatch.setattr(business_date, "utc_now", lambda: instant[0])
    login_client(raw_client)
    old = business_date.today()
    new = old + timedelta(days=1)
    account = raw_client.get("/api/accounts").json()[0]["id"]
    assert (
        raw_client.post("/api/budgets", json={"category": "Boundary", "monthly_limit": "100"}).status_code
        == 201
    )
    schedule = raw_client.post(
        "/api/recurring",
        json={
            "start_date": old.isoformat(),
            "type": "income",
            "category": "Boundary",
            "amount": "10",
            "frequency": "daily",
        },
    )
    assert schedule.status_code == 201
    entry = {"date": new.isoformat(), "type": "expense", "category": "Boundary", "amount": "2"}
    statement = {"account_id": account, "closing_date": new.isoformat(), "closing_balance": "8"}
    assert raw_client.post("/api/transactions", json=entry).status_code == 400
    assert raw_client.post("/api/reconciliations", json=statement).status_code == 400
    assert process_recurring(app.state.database) == 0
    assert raw_client.get("/api/dashboard").json()["period"]["end"] == old.isoformat()
    assert raw_client.get("/api/budgets").json()[0]["month_year"] == old.strftime("%Y-%m")
    assert raw_client.get("/api/reports/monthly").json()["months"][-1]["month"] == old.strftime("%Y-%m")

    instant[0] = end
    policy = raw_client.get("/api/ledger-policy").json()
    assert policy == {
        "business_date": new.isoformat(),
        "business_timezone": "Europe/Belgrade",
        "model": "posted-only",
    }
    assert process_recurring(app.state.database) == 1
    assert process_recurring(app.state.database) == 0
    assert raw_client.post("/api/transactions", json=entry).status_code == 201
    assert raw_client.post("/api/reconciliations", json=statement).status_code == 201
    assert raw_client.get("/api/budgets").json() == []
    assert (
        raw_client.post("/api/budgets", json={"category": "Boundary", "monthly_limit": "100"}).status_code
        == 201
    )
    budget = raw_client.get("/api/budgets").json()[0]
    assert budget["month_year"] == new.strftime("%Y-%m")
    assert budget["spent"] == 2
    report = raw_client.get("/api/reports/monthly").json()
    assert report["months"][-1]["month"] == new.strftime("%Y-%m")
    dashboard = raw_client.get("/api/dashboard").json()
    assert dashboard["period"]["end"] == new.isoformat()
    assert dashboard["balance"] == 8
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM recurring_occurrences").fetchone()[0] == 1


@pytest.mark.parametrize("direct", [False, True])
def test_worker_pass_reads_clock_once_across_midnight(raw_client, monkeypatch, direct):
    reads = []

    def moving_clock():
        instant = datetime(2026, 9, 30, 21, 59, 59, tzinfo=UTC) + timedelta(seconds=len(reads))
        reads.append(instant)
        return instant

    monkeypatch.setattr(business_date, "utc_now", moving_clock)

    def process():
        if direct:
            from app.repositories.recurring_repository import RecurringRepository

            with app.state.database.connection() as conn:
                return RecurringRepository(conn).process_due()
        return process_recurring(app.state.database)

    assert process() == 0
    assert len(reads) == 1
    assert process() == 0
    assert len(reads) == 2


@pytest.mark.parametrize("instant", ["2026-03-29T00:59:59+00:00", "2026-10-25T00:59:59+00:00"])
def test_dst_transition_does_not_repeat_recurring_occurrence(raw_client, monkeypatch, instant):
    value = [datetime.fromisoformat(instant)]
    monkeypatch.setattr(business_date, "utc_now", lambda: value[0])
    login_client(raw_client)
    day = business_date.today()
    response = raw_client.post(
        "/api/recurring",
        json={
            "start_date": (day - timedelta(days=1)).isoformat(),
            "type": "income",
            "category": "DST",
            "amount": "5",
            "frequency": "daily",
        },
    )
    assert response.status_code == 201
    assert process_recurring(app.state.database) == 1
    value[0] += timedelta(seconds=1)
    assert business_date.today() == day
    assert process_recurring(app.state.database) == 0
    assert raw_client.get("/api/dashboard").json()["balance"] == 5


def test_configured_zone_not_host_controls_date(monkeypatch):
    instant = datetime(2026, 9, 30, 22, tzinfo=UTC)
    monkeypatch.setattr(business_date, "utc_now", lambda: instant)
    monkeypatch.setattr(settings, "business_timezone", "UTC")
    assert business_date.today() == date(2026, 9, 30)
    monkeypatch.setattr(settings, "business_timezone", "Europe/Belgrade")
    assert business_date.today() == date(2026, 10, 1)
