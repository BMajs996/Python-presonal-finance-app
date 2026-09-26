import pytest
from app.main import app
from fastapi.testclient import TestClient


def test_populated_response_contracts_preserve_service_payloads(client):
    from datetime import date

    from app.repositories.finance_repository import FinanceRepository
    from app.services.finance_service import FinanceService

    account = client.post("/api/accounts", json={"name": "Contract savings"}).json()
    transaction = {
        "date": date.today().isoformat(),
        "type": "expense",
        "category": "Food",
        "amount": 12.34,
        "description": "Lunch",
        "account_id": account["id"],
    }
    created = client.post("/api/transactions", json=transaction)
    assert created.status_code == 201
    assert client.put(f"/api/transactions/{created.json()['id']}", json=transaction).status_code == 200
    budget = client.post("/api/budgets", json={"category": "Food", "monthly_limit": 100})
    assert budget.status_code == 201
    assert (
        client.put(
            f"/api/budgets/{budget.json()['id']}", json={"category": "Food", "monthly_limit": 150}
        ).status_code
        == 200
    )
    recurring = client.post(
        "/api/recurring",
        json={
            "type": "expense",
            "category": "Rent",
            "amount": 50,
            "frequency": "monthly",
            "start_date": "2099-01-01",
        },
    )
    assert recurring.status_code == 201
    assert (
        client.put(
            f"/api/recurring/{recurring.json()['id']}",
            json={
                "type": "expense",
                "category": "Rent",
                "amount": 60,
                "frequency": "monthly",
                "next_date": "2099-02-01",
            },
        ).status_code
        == 200
    )
    main_id = next(a["id"] for a in client.get("/api/accounts").json() if a["name"] == "Main Account")
    assert (
        client.post(
            "/api/transfers",
            json={
                "date": date.today().isoformat(),
                "from_account_id": main_id,
                "to_account_id": account["id"],
                "amount": 1.23,
            },
        ).status_code
        == 201
    )

    database = app.state.database
    with database.connection() as connection:
        service = FinanceService(FinanceRepository(database, connection=connection))
        items, total = service.list_transactions()
        expected = {
            "/api/transactions": {"items": items, "total": total},
            "/api/accounts": service.accounts(),
            "/api/budgets": service.budgets(),
            "/api/recurring": service.recurring(),
            "/api/transfers": service.transfers(),
            "/api/dashboard": service.dashboard(),
            "/api/reports/monthly": service.monthly_report(),
            "/api/categories": service.categories(),
        }
        for path, payload in expected.items():
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.json() == payload, path


def test_domain_errors_keep_detail_contract_and_status_codes(client):
    from datetime import date

    duplicate = client.post("/api/accounts", json={"name": "Main Account"})
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "An account with this name already exists"}
    invalid = client.post(
        "/api/transactions",
        json={
            "date": date.today().isoformat(),
            "type": "income",
            "category": "Salary",
            "amount": 10,
            "account_id": 99999,
        },
    )
    assert invalid.status_code == 400
    assert isinstance(invalid.json()["detail"], str)
    assert client.delete("/api/transactions/99999").json() == {"detail": "Transaction not found"}
    assert client.delete("/api/accounts/99999").status_code == 404
    assert client.get("/api/transactions?date_start=2026-09-20&date_end=2026-09-01").status_code == 400
    invalid_input = client.post("/api/transactions", json={})
    assert invalid_input.status_code == 422
    assert isinstance(invalid_input.json()["detail"], list)


def test_duplicate_budget_update_returns_conflict_without_changing_budget(client):
    first = client.post("/api/budgets", json={"category": "Food", "monthly_limit": 100}).json()
    client.post("/api/budgets", json={"category": "Travel", "monthly_limit": 200})
    response = client.put(f"/api/budgets/{first['id']}", json={"category": "Travel", "monthly_limit": 50})
    assert response.status_code == 409
    assert response.json() == {"detail": "A budget for this category already exists"}
    assert first in client.get("/api/budgets").json()


def test_openapi_declares_every_json_success_and_domain_error(client):
    schema = client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/"):
            continue
        for operation in operations.values():
            for code, response in operation["responses"].items():
                if code.startswith("2") and code != "204":
                    assert response["content"]["application/json"]["schema"], path
            if path != "/api/health":
                for code in ("400", "404", "409"):
                    assert operation["responses"][code]["content"]["application/json"]["schema"] == {
                        "$ref": "#/components/schemas/ErrorResponse"
                    }


def test_unexpected_value_errors_are_not_reported_as_bad_requests(client):
    from app.api.dependencies import get_finance_service

    def broken_dependency():
        raise ValueError("Unexpected internal bug")

    app.dependency_overrides[get_finance_service] = broken_dependency
    try:
        with pytest.raises(ValueError, match="Unexpected internal bug"):
            client.get("/api/accounts")
    finally:
        app.dependency_overrides.pop(get_finance_service)


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
    from datetime import date

    client.post(
        "/api/transactions",
        json={
            "date": date.today().isoformat(),
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


def test_transaction_recovery_and_history_api(client):
    payload = {"date": "2026-09-25", "type": "expense", "category": "Food", "amount": 12.34}
    entry = client.post("/api/transactions", json=payload).json()
    url = f"/api/transactions/{entry['id']}"
    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 404
    assert client.put(url, json=payload).status_code == 404
    deleted = client.get("/api/transactions/deleted").json()
    assert deleted["total"] == 1
    assert deleted["items"][0]["deleted_at"]
    history = client.get(url + "/history?limit=1").json()
    assert history["total"] == 2
    assert len(history["items"]) == 1
    assert history["items"][0]["action"] == "deleted"
    assert history["items"][0]["before_state"]["amount_cents"] == 1234
    assert client.post(url + "/restore").json() == entry
    assert client.post(url + "/restore").json() == entry
    assert client.get(url + "/history").json()["total"] == 3
    assert client.get("/api/transactions/deleted").json() == {"items": [], "total": 0}
    assert client.get("/api/transactions").json()["items"] == [entry]
    assert client.post("/api/transactions/99999/restore").status_code == 404
    assert client.get("/api/transactions/99999/history").status_code == 404
    for path in ("/api/transactions/deleted", url + "/history"):
        assert client.get(path + "?limit=0").status_code == 422
        assert client.get(path + "?offset=-1").status_code == 422
