from app.main import app
from app.repositories.reconciliation_repository import ReconciliationRepository

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


def test_large_ledger_is_paged_and_clear_returns_only_totals(raw_client, monkeypatch):
    login_client(raw_client)
    account = raw_client.get("/api/accounts").json()[0]["id"]
    with app.state.database.connection() as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for index in range(10000):
            conn.execute(
                """INSERT INTO transactions(date,type,category,amount,amount_cents,description,account_id)
                VALUES ('2020-01-01','income','Test',0.01,1,?,?)""",
                (f"Row {index}", account),
            )

    def no_history_scan(*args):
        raise AssertionError("Statement creation must not load account history")

    monkeypatch.setattr(ReconciliationRepository, "list", no_history_scan)
    response = raw_client.post(
        "/api/reconciliations",
        json={
            "account_id": account,
            "closing_date": "2020-01-31",
            "closing_balance": "100",
        },
    )
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["total_entries"] == 10000
    assert len(first["entries"]) == 100
    assert first["next_cursor"]
    next_page = raw_client.get(
        f"/api/reconciliations/{first['id']}", params={"cursor": first["next_cursor"], "limit": 200}
    ).json()
    assert len(next_page["entries"]) == 200
    assert not {row["entry_id"] for row in first["entries"]} & {
        row["entry_id"] for row in next_page["entries"]
    }

    def no_ledger_scan(*args):
        raise AssertionError("Clearing must not fetch ledger entries")

    monkeypatch.setattr(ReconciliationRepository, "entries", no_ledger_scan)
    response = raw_client.put(
        f"/api/reconciliations/{first['id']}/entries",
        json={
            "kind": "transaction",
            "entry_id": next_page["entries"][-1]["entry_id"],
            "cleared": True,
        },
    )
    assert response.status_code == 200, response.text
    assert "entries" not in response.json()
    assert response.json()["cleared_balance_cents"] == 1
    assert response.json()["cleared_count"] == 1
    assert response.json()["total_entries"] == 10000
    for params in ({"cursor": "bad"}, {"limit": 201}, {"limit": 0}):
        assert raw_client.get(f"/api/reconciliations/{first['id']}", params=params).status_code == 422
