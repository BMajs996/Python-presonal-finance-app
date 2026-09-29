import json
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from app.core.config import settings
from app.domain import business_date
from app.domain.category import canonical_key
from app.domain.money import Money, money_contract
from app.main import app
from app.maintenance import main
from app.services.category_review import review_categories
from app.services.read_only_database import read_only_database

from .conftest import login_client
from .postgres_helpers import pg_url as pg_url
from .test_auth import raw_client as raw_client


def transaction(category, amount="1.01"):
    return {
        "date": business_date.today().isoformat(),
        "type": "expense",
        "category": category,
        "amount": amount,
    }


@pytest.mark.parametrize(
    "variants,key",
    [
        (["Food", " food ", "FOOD"], "food"),
        (["Travel  Food", "Travel\tFood", "Travel\u00a0Food"], "travel food"),
        (["Caf\u00e9", "Cafe\u0301", "CAF\u00c9"], "caf\u00e9"),
        (["Stra\u00dfe", "STRASSE"], "strasse"),
    ],
)
def test_canonical_key_policy(variants, key):
    assert {canonical_key(value) for value in variants} == {key}


def test_category_variants_agree_across_import_budgets_reports(raw_client):
    login_client(raw_client)
    categories = ["Food", "food", "FOOD", "Travel  Food", "Travel Food", "Caf\u00e9", "Cafe\u0301"]
    rows = [transaction(value) for value in categories]
    rows.append(transaction(" Food "))
    preview = raw_client.post("/api/transactions/import/preview", json={"rows": rows})
    assert preview.status_code == 200
    assert [row["status"] for row in preview.json()["rows"]] == ["valid"] * 7 + ["duplicate"]
    imported = raw_client.post("/api/transactions/import", json={"batch_id": str(uuid4()), "rows": rows})
    assert imported.json() == {"imported": 7, "duplicates": 1}
    again = raw_client.post("/api/transactions/import/preview", json={"rows": rows}).json()
    assert all(row["status"] == "duplicate" for row in again["rows"])
    for category in categories:
        response = raw_client.post("/api/budgets", json={"category": category, "monthly_limit": "10"})
        assert response.status_code == 201
        assert response.json()["spent"] == 1.01
    report = raw_client.get("/api/reports/monthly").json()
    assert {row["category"] for row in report["top_categories"]} == set(categories)
    assert all(row["money"]["values"]["total"] == "1.01" for row in report["top_categories"])
    assert report["summary"]["money"]["values"]["expenses"] == "7.07"
    assert (
        raw_client.post("/api/budgets", json={"category": " \t ", "monthly_limit": "10"}).status_code == 422
    )


def test_category_review_preserves_rows_totals_and_audit(raw_client, capsys):
    login_client(raw_client)
    for name in ["Food", "food", "FOOD"]:
        assert raw_client.post("/api/transactions", json=transaction(name)).status_code == 201
        assert (
            raw_client.post("/api/budgets", json={"category": name, "monthly_limit": "10"}).status_code == 201
        )

    def snapshot():
        with app.state.database.connection() as conn:
            return {
                table: [dict(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY id")]
                for table in ("transactions", "budgets", "transaction_audit")
            }

    before = snapshot()
    assert main(["review-categories", "--limit", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total_collisions"] == 1
    assert [item["display_name"] for item in report["items"][0]["variants"]] == ["FOOD", "Food", "food"]
    assert {(row["source"], row["row_count"], row["amount_cents"]) for row in report["baseline"]} == {
        ("transaction", 3, "303"),
        ("budget", 3, "3000"),
    }
    assert snapshot() == before
    url = settings.database_url.get_secret_value() if settings.database_url else None
    assert review_categories(settings.database_path, url, offset=1)["items"] == []
    with read_only_database(settings.database_path, url) as conn:
        with pytest.raises((sqlite3.OperationalError, psycopg.errors.ReadOnlySqlTransaction)):
            conn.execute("DELETE FROM budgets")
    assert snapshot() == before


@pytest.mark.parametrize(
    "cents",
    [
        0,
        1,
        -1,
        100_000_000_000,
        -100_000_000_000,
        9_000_000_000_000_000,
        -9_000_000_000_000_000,
        9_007_199_254_740_993,
        -18_000_000_000_000_001,
    ],
)
def test_exact_wire_roundtrip_python_and_javascript(cents):
    value = Money(cents).as_decimal_string()
    assert Decimal(value) * 100 == cents
    contract = money_contract("USD", amount=cents)
    script = """
        import { decimalToCents, centsToDecimal } from './frontend/utils/exact-money.js';
        import { readFileSync } from 'node:fs';
        const body = JSON.parse(readFileSync(0, 'utf8'));
        process.stdout.write(centsToDecimal(decimalToCents(body.values.amount)));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(contract),
        text=True,
        capture_output=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.stdout == value


def test_additive_money_contract_covers_all_financial_views(raw_client):
    login_client(raw_client)
    main_account = raw_client.get("/api/accounts").json()[0]["id"]
    account = raw_client.post(
        "/api/accounts", json={"name": "Negative", "opening_balance": "-1000000000.00"}
    ).json()
    assert account["opening_balance"] == -1_000_000_000
    assert account["money"]["values"]["opening_balance"] == "-1000000000.00"
    created = raw_client.post("/api/transactions", json=transaction("Food", "1000000000.00")).json()
    assert created["amount"] == 1_000_000_000
    assert created["money"]["values"]["amount"] == "1000000000.00"
    transfer = raw_client.post(
        "/api/transfers",
        json={
            "date": business_date.today().isoformat(),
            "amount": "1000000000.00",
            "from_account_id": main_account,
            "to_account_id": account["id"],
        },
    ).json()
    assert transfer["money"]["values"]["amount"] == "1000000000.00"
    schedule = raw_client.post(
        "/api/recurring",
        json={
            "start_date": business_date.today().isoformat(),
            "type": "expense",
            "category": "Food",
            "amount": "0.01",
            "frequency": "monthly",
        },
    ).json()
    assert schedule["money"]["values"]["amount"] == "0.01"
    budget = raw_client.post("/api/budgets", json={"category": "Food", "monthly_limit": "100"}).json()
    assert budget["money"]["values"] == {"monthly_limit": "100.00", "spent": "1000000000.00"}
    dashboard = raw_client.get("/api/dashboard").json()
    assert dashboard["money"]["values"]["balance"] == "-2000000000.00"
    assert dashboard["balance"] == -2_000_000_000
    assert dashboard["balance_history"][-1]["money"]["values"]["balance"] == "-2000000000.00"
    report = raw_client.get("/api/reports/monthly").json()
    assert report["months"][-1]["money"]["values"]["balance"] == "-2000000000.00"
    assert report["category_trends"][0]["money"]["values"]["totals"][-1] == "1000000000.00"
    statement = raw_client.post(
        "/api/reconciliations",
        json={
            "account_id": main_account,
            "closing_date": business_date.today().isoformat(),
            "closing_balance": "-90000000000000.00",
        },
    ).json()
    assert statement["money"]["values"]["closing_balance"] == "-90000000000000.00"
    assert statement["entries"][0]["money"]["version"] == "decimal-v1"
    history = raw_client.get(f"/api/transactions/{created['id']}/history").json()
    assert history["items"][0]["after_state"]["money"]["values"]["amount"] == "1000000000.00"


@pytest.mark.parametrize("limit,offset", [(0, 0), (1001, 0), (1, -1)])
def test_category_review_bounds_and_missing_database(tmp_path, limit, offset):
    with pytest.raises(ValueError, match="limit"):
        review_categories(tmp_path / "missing.db", limit=limit, offset=offset)
    with pytest.raises(sqlite3.OperationalError):
        review_categories(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_review_includes_deleted_history_and_inactive_schedules(raw_client):
    login_client(raw_client)
    created = raw_client.post("/api/transactions", json=transaction("Food")).json()
    assert raw_client.delete(f"/api/transactions/{created['id']}").status_code == 204
    schedule = raw_client.post(
        "/api/recurring",
        json={
            "start_date": business_date.today().isoformat(),
            "type": "expense",
            "category": "FOOD",
            "amount": "2.02",
            "frequency": "monthly",
        },
    ).json()
    assert raw_client.delete(f"/api/recurring/{schedule['id']}").status_code == 204
    url = settings.database_url.get_secret_value() if settings.database_url else None
    report = review_categories(settings.database_path, url)
    assert report["total_collisions"] == 1
    assert {
        (row["source"], row["state"], row["row_count"], row["amount_cents"]) for row in report["baseline"]
    } == {
        ("transaction", "deleted", 1, "101"),
        ("recurring", "inactive", 1, "202"),
    }


def test_exact_balance_adapter_never_uses_float_as_source():
    from types import SimpleNamespace

    from app.domain.date_range import DateRange
    from app.services.balance_service import BalanceService

    cents = -9_007_199_254_740_993
    repo = SimpleNamespace(
        base_currency="USD",
        total_cents=lambda: cents,
        daily_history_cents=lambda period: (cents, []),
        monthly_history_cents=lambda labels: (cents, {}),
    )
    service = BalanceService(repo)
    assert service.total_money().as_decimal_string() == "-90071992547409.93"
    assert isinstance(service.total(), float)
    assert isinstance(service.monthly_history(["2026-01"])["2026-01"], float)
    history = service.daily_history(DateRange.trailing(1))
    assert history[0]["money"]["values"]["balance"] == "-90071992547409.93"


def test_missing_legacy_audit_currency_is_not_invented():
    from app.schemas import TransactionSnapshot

    snapshot = TransactionSnapshot.model_validate(
        {
            "id": 1,
            "date": "2020-01-01",
            "type": "income",
            "category": "Legacy",
            "amount_cents": 123,
            "description": None,
            "account_id": None,
            "account_name": None,
            "currency": None,
            "deleted_at": None,
        }
    )
    assert snapshot.money is None
    assert snapshot.amount_cents == 123
