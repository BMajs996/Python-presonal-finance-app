from uuid import uuid4

from app.main import app

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


def row(**changes):
    return {
        "date": "2026-01-01",
        "type": "expense",
        "category": "Food",
        "amount": "12.34",
        "description": "Lunch",
        **changes,
    }


def test_csv_preview_and_atomic_idempotent_commit(raw_client):
    login_client(raw_client)
    rows = [row(), row(), row(category="Travel")]
    preview = raw_client.post("/api/transactions/import/preview", json={"rows": rows})
    assert preview.status_code == 200
    assert [item["status"] for item in preview.json()["rows"]] == ["valid", "duplicate", "valid"]
    payload = {"batch_id": str(uuid4()), "rows": rows}
    response = raw_client.post("/api/transactions/import", json=payload)
    assert response.status_code == 200
    assert response.json() == {"imported": 2, "duplicates": 1}
    assert raw_client.post("/api/transactions/import", json=payload).json() == response.json()
    assert raw_client.get("/api/transactions").json()["total"] == 2
    # A fresh batch still detects rows committed by a different tab or importer.
    payload["batch_id"] = str(uuid4())
    assert raw_client.post("/api/transactions/import", json=payload).json() == {
        "imported": 0,
        "duplicates": 3,
    }
    payload["rows"] = [row(amount="15")]
    assert raw_client.post("/api/transactions/import", json=payload).status_code == 409


def test_csv_failure_rolls_back_financial_rows_audit_and_receipt(raw_client):
    login_client(raw_client)
    payload = {"batch_id": str(uuid4()), "rows": [row(), row(account_id=999999)]}
    response = raw_client.post("/api/transactions/import", json=payload)
    assert response.status_code == 409
    assert "Row 2" in response.json()["detail"]
    assert raw_client.get("/api/transactions").json()["total"] == 0
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transaction_audit").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'csv-import:%'").fetchone()[0] == 0
    payload["rows"] = [row()]
    assert raw_client.post("/api/transactions/import", json=payload).json()["imported"] == 1


def test_csv_preview_reports_missing_account_and_rejects_oversized_batches(raw_client):
    login_client(raw_client)
    response = raw_client.post("/api/transactions/import/preview", json={"rows": [row(account_id=999999)]})
    assert response.json()["rows"][0]["status"] == "invalid"
    for rows in ([], [row()] * 1001):
        response = raw_client.post("/api/transactions/import", json={"batch_id": str(uuid4()), "rows": rows})
        assert response.status_code == 422
    assert (
        raw_client.post("/api/transactions/import", json={"batch_id": "bad", "rows": [row()]}).status_code
        == 422
    )


def test_csv_concurrent_retry_creates_one_batch(raw_client):
    from concurrent.futures import ThreadPoolExecutor

    login_client(raw_client)
    payload = {"batch_id": str(uuid4()), "rows": [row()]}
    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [
            workers.submit(raw_client.post, "/api/transactions/import", json=payload) for _ in range(4)
        ]
        for future in futures:
            assert future.result(timeout=10).json() == {"imported": 1, "duplicates": 0}
    assert raw_client.get("/api/transactions").json()["total"] == 1
