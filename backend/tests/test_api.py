import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "database_path", tmp_path / "api-test.db")

    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_get_update_delete_transaction(client):
    payload = {
        "date": "2026-08-23",
        "type": "expense",
        "category": "Food",
        "amount": 42.50,
        "description": "Dinner",
    }

    created = client.post("/api/transactions", json=payload)
    assert created.status_code == 201

    transaction = created.json()
    transaction_id = transaction["id"]

    fetched = client.get("/api/transactions")
    assert fetched.status_code == 200
    assert fetched.json()["total"] == 1
    assert fetched.json()["items"][0]["category"] == "Food"

    updated = client.put(
        f"/api/transactions/{transaction_id}",
        json={**payload, "amount": 55},
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == 55

    deleted = client.delete(f"/api/transactions/{transaction_id}")
    assert deleted.status_code == 204

    assert client.get("/api/transactions").json()["total"] == 0


def test_create_transaction_rejects_invalid_amount(client):
    response = client.post(
        "/api/transactions",
        json={
            "date": "2026-08-23",
            "type": "expense",
            "category": "Food",
            "amount": 0,
            "description": "Invalid",
        },
    )

    assert response.status_code == 422


def test_create_transaction_rejects_invalid_type(client):
    response = client.post(
        "/api/transactions",
        json={
            "date": "2026-08-23",
            "type": "transfer",
            "category": "Food",
            "amount": 10,
        },
    )

    assert response.status_code == 422


def test_missing_transaction_returns_404(client):
    response = client.put(
        "/api/transactions/999999",
        json={
            "date": "2026-08-23",
            "type": "expense",
            "category": "Food",
            "amount": 10,
        },
    )

    assert response.status_code == 404


def test_dashboard_endpoint(client):
    client.post(
        "/api/transactions",
        json={
            "date": "2026-08-23",
            "type": "income",
            "category": "Salary",
            "amount": 1000,
        },
    )

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["income"] == 1000
    assert body["balance"] == 1000


def test_categories_endpoint(client):
    client.post(
        "/api/transactions",
        json={
            "date": "2026-08-23",
            "type": "expense",
            "category": "Food",
            "amount": 10,
        },
    )

    response = client.get("/api/categories")

    assert response.status_code == 200
    assert response.json() == ["Food"]


def test_budget_api(client):
    response = client.post(
        "/api/budgets",
        json={"category": "Food", "monthly_limit": 500},
    )

    assert response.status_code == 201
    assert response.json()["monthly_limit"] == 500

    budgets = client.get("/api/budgets")
    assert budgets.status_code == 200
    assert len(budgets.json()) == 1


def test_recurring_api(client):
    response = client.post(
        "/api/recurring",
        json={
            "type": "expense",
            "category": "Rent",
            "amount": 800,
            "description": "Monthly rent",
            "frequency": "monthly",
            "start_date": "2026-08-01",
        },
    )

    assert response.status_code == 201
    assert response.json()["category"] == "Rent"

    recurring = client.get("/api/recurring")
    assert recurring.status_code == 200
    assert len(recurring.json()) == 1


def test_root_page_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Finance Dashboard" in response.text


def test_accounts_api(client):
    response = client.get("/api/accounts")
    assert response.status_code == 200
    accounts = response.json()
    assert len(accounts) == 1
    assert accounts[0]["name"] == "Main Account"

    created = client.post(
        "/api/accounts",
        json={"name": "Savings", "type": "savings", "opening_balance": 1000},
    )
    assert created.status_code == 201
    assert created.json()["balance"] == 1000


def test_transaction_can_be_assigned_to_account(client):
    account = client.post(
        "/api/accounts",
        json={"name": "Cash", "type": "cash"},
    ).json()

    response = client.post(
        "/api/transactions",
        json={
            "date": "2026-08-23",
            "type": "expense",
            "category": "Food",
            "amount": 25,
            "account_id": account["id"],
        },
    )

    assert response.status_code == 201
    assert response.json()["account_name"] == "Cash"


def test_transfer_api_does_not_create_income_or_expense(client):
    first = client.post(
        "/api/accounts",
        json={"name": "Checking", "type": "checking"},
    ).json()
    second = client.post(
        "/api/accounts",
        json={"name": "Savings", "type": "savings"},
    ).json()

    response = client.post(
        "/api/transfers",
        json={
            "date": "2026-08-23",
            "from_account_id": first["id"],
            "to_account_id": second["id"],
            "amount": 500,
            "description": "Savings transfer",
        },
    )
    assert response.status_code == 201

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["income"] == 0
    assert dashboard["expenses"] == 0
    assert dashboard["net"] == 0
    assert dashboard["balance"] == 0

    transfers = client.get("/api/transfers").json()
    assert len(transfers) == 1
    assert transfers[0]["from_account_name"] == "Checking"
    assert transfers[0]["to_account_name"] == "Savings"


def test_transfer_rejects_same_account(client):
    account = client.get("/api/accounts").json()[0]
    response = client.post(
        "/api/transfers",
        json={
            "date": "2026-08-23",
            "from_account_id": account["id"],
            "to_account_id": account["id"],
            "amount": 100,
        },
    )
    assert response.status_code == 400
