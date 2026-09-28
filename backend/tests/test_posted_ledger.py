import json
from datetime import date, timedelta
from uuid import uuid4

import pytest
from app.core.config import settings
from app.domain import business_date
from app.main import app
from app.maintenance import main
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.transfer_repository import TransferRepository
from app.schemas import TransactionCreate, TransferCreate
from app.services.future_entry_review import review_future_entries

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


@pytest.fixture
def clock(monkeypatch):
    value = [date(2026, 9, 10)]

    class Clock(date):
        @classmethod
        def today(cls):
            return value[0]

    monkeypatch.setattr(business_date, "date", Clock)
    return value


def payload(day, kind="income", amount="100.00", account_id=None):
    return {
        "date": day.isoformat(),
        "type": kind,
        "amount": amount,
        "category": "Food",
        "account_id": account_id,
    }


@pytest.mark.parametrize("kind", ["income", "expense"])
def test_future_create_edit_and_csv_are_rejected_without_writes(raw_client, clock, kind):
    login_client(raw_client)
    future = payload(clock[0] + timedelta(days=1), kind)
    response = raw_client.post("/api/transactions", json=future)
    assert response.status_code == 400
    assert "Future-dated" in response.json()["detail"]
    posted = raw_client.post("/api/transactions", json=payload(clock[0], kind))
    assert posted.status_code == 201
    ident = posted.json()["id"]
    assert raw_client.put(f"/api/transactions/{ident}", json=future).status_code == 400
    rows = [payload(clock[0], kind, "1.00"), future]
    preview = raw_client.post("/api/transactions/import/preview", json={"rows": rows})
    assert [row["status"] for row in preview.json()["rows"]] == ["valid", "invalid"]
    result = raw_client.post("/api/transactions/import", json={"batch_id": str(uuid4()), "rows": rows})
    assert result.status_code == 400
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM transaction_audit").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'csv-import:%'").fetchone()[0] == 0
    assert raw_client.get("/api/transactions").json()["items"][0]["date"] == clock[0].isoformat()


def test_future_transfer_and_restore_are_rejected_but_recurring_can_plan(raw_client, clock):
    login_client(raw_client)
    first = raw_client.get("/api/accounts").json()[0]["id"]
    second = raw_client.post("/api/accounts", json={"name": "Savings"}).json()["id"]
    future = clock[0] + timedelta(days=30)
    assert (
        raw_client.post(
            "/api/transfers",
            json={
                "date": future.isoformat(),
                "from_account_id": first,
                "to_account_id": second,
                "amount": "25",
            },
        ).status_code
        == 400
    )
    with app.state.database.connection() as conn:
        repo = TransactionRepository(conn)
        row = repo.add(TransactionCreate(**payload(future)))
        repo.delete(row["id"])
    assert raw_client.post(f"/api/transactions/{row['id']}/restore").status_code == 400
    assert raw_client.get("/api/transactions/deleted").json()["total"] == 1
    response = raw_client.post(
        "/api/recurring",
        json={
            "start_date": future.isoformat(),
            "type": "income",
            "category": "Plan",
            "frequency": "monthly",
            "amount": "100",
        },
    )
    assert response.status_code == 201
    assert raw_client.get("/api/dashboard").json()["balance"] == 0


def test_legacy_future_rows_become_effective_once_across_all_posted_views(raw_client, clock, capsys):
    login_client(raw_client)
    first = raw_client.get("/api/accounts").json()[0]["id"]
    second = raw_client.post("/api/accounts", json={"name": "Savings"}).json()["id"]
    assert (
        raw_client.post("/api/budgets", json={"category": "Food", "monthly_limit": "100"}).status_code == 201
    )
    tomorrow = clock[0] + timedelta(days=1)
    with app.state.database.connection() as conn:
        transactions = TransactionRepository(conn)
        income = transactions.add(TransactionCreate(**payload(tomorrow, account_id=first)))
        expense = transactions.add(TransactionCreate(**payload(tomorrow, "expense", "20", first)))
        transfer = TransferRepository(conn).add(
            TransferCreate(
                date=tomorrow,
                from_account_id=first,
                to_account_id=second,
                amount="30",
            )
        )

    before = raw_client.get("/api/dashboard").json()
    assert before["balance"] == before["income"] == before["expenses"] == 0
    assert before["recent_transactions"] == []
    assert all(point["balance"] == 0 for point in before["balance_history"])
    assert [row["balance"] for row in raw_client.get("/api/accounts").json()] == [0, 0]
    assert raw_client.get("/api/transactions").json()["total"] == 0
    assert raw_client.get("/api/transactions", params={"date_end": tomorrow.isoformat()}).json()["total"] == 0
    assert raw_client.get("/api/categories").json() == []
    assert raw_client.get("/api/transfers").json() == []
    report = raw_client.get("/api/reports/monthly").json()
    assert report["summary"]["income"] == report["summary"]["expenses"] == 0
    assert report["top_categories"] == []
    assert report["months"][-1]["balance"] == 0
    assert raw_client.get("/api/budgets").json()[0]["spent"] == 0
    assert main(["review-future"]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["total"] == 3
    assert {(r["kind"], r["id"]) for r in review["items"]} == {
        ("transaction", income["id"]),
        ("transaction", expense["id"]),
        ("transfer", transfer["id"]),
    }

    clock[0] = tomorrow
    for _ in range(2):
        data = raw_client.get("/api/dashboard").json()
        assert data["balance"] == 80
        assert data["income"] == 100
        assert data["expenses"] == 20
        assert data["balance_history"][-1]["balance"] == 80
        assert len(data["recent_transactions"]) == 2
        accounts = {r["id"]: r for r in raw_client.get("/api/accounts").json()}
        assert accounts[first]["balance"] == 50
        assert accounts[second]["balance"] == 30
        assert accounts[first]["transaction_count"] == 2
        assert raw_client.get("/api/transactions").json()["total"] == 2
        assert len(raw_client.get("/api/transfers").json()) == 1
        report = raw_client.get("/api/reports/monthly").json()
        assert report["summary"]["net"] == 80
        assert report["months"][-1]["balance"] == 80
        assert report["top_categories"] == [{"category": "Food", "total": 20}]
        assert raw_client.get("/api/budgets").json()[0]["spent"] == 20
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transaction_audit").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_review_is_read_only_and_can_page(raw_client, clock):
    login_client(raw_client)
    with app.state.database.connection() as conn:
        row = TransactionRepository(conn).add(TransactionCreate(**payload(clock[0] + timedelta(days=1))))
    url = settings.database_url.get_secret_value() if settings.database_url else None
    result = review_future_entries(settings.database_path, url, limit=1)
    assert result["total"] == 1 and result["items"][0]["id"] == row["id"]
    assert review_future_entries(settings.database_path, url, limit=1, offset=1)["items"] == []
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM transaction_audit").fetchone()[0] == 1


def test_review_does_not_create_missing_sqlite_database(tmp_path):
    import sqlite3

    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        review_future_entries(path)
    assert not path.exists()


@pytest.mark.parametrize("limit,offset", [(0, 0), (1001, 0), (1, -1)])
def test_review_bounds_output(tmp_path, limit, offset):
    with pytest.raises(ValueError, match="limit"):
        review_future_entries(tmp_path / "missing.db", limit=limit, offset=offset)
