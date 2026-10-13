from contextlib import ExitStack

import pytest
from app.core.config import settings
from app.domain import business_date
from app.main import app
from app.services.user_account_service import UserAccountService
from fastapi.testclient import TestClient
from pydantic import SecretStr

from .postgres_helpers import pg_url as pg_url
from .test_user_accounts import NEW_PASSWORD, PASSWORD


@pytest.fixture(params=["sqlite", "postgres"])
def clients(request, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "accounts-api.db")
    if request.param == "postgres":
        monkeypatch.setattr(settings, "database_url", SecretStr(request.getfixturevalue("pg_url")))
    with TestClient(app) as owner, ExitStack() as stack:
        owner.headers["Origin"] = "http://testserver"
        service = UserAccountService(app.state.database)
        members = []
        for name in ("alice", "bob"):
            client = TestClient(app)
            stack.callback(client.close)
            client.headers["Origin"] = "http://testserver"
            token = service.issue_code("invite", name + "@example.com")
            response = client.post(
                "/api/auth/register",
                json={
                    "token": token,
                    "username": name,
                    "display_name": name.title(),
                    "email": name + "@example.com",
                    "phone": "+381641234567",
                    "password": PASSWORD,
                },
            )
            assert response.status_code == 201, response.text
            assert "password_hash" not in response.text and token not in response.text
            login = client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
            assert login.status_code == 200, login.text
            session = login.json()
            client.headers["X-CSRF-Token"] = session["csrf_token"]
            members.append((client, session))
        yield owner, service, members


def test_real_member_sessions_enforce_data_and_operation_isolation(clients):
    _owner, _service, members = clients
    alice, first = members[0]
    bob, second = members[1]
    assert first["user_id"] != second["user_id"]
    assert first["is_admin"] is False and second["is_admin"] is False
    data = {
        "date": business_date.today().isoformat(),
        "type": "income",
        "category": "Salary",
        "amount": "12.34",
    }
    created = alice.post("/api/transactions", json=data)
    assert created.status_code == 201
    ident = created.json()["id"]
    assert alice.get("/api/transactions").json()["total"] == 1
    assert bob.get("/api/transactions").json()["total"] == 0
    assert bob.get("/api/dashboard").json()["money"]["values"]["balance"] == "0.00"
    assert bob.get(f"/api/transactions/{ident}/history").status_code == 404
    assert bob.put(f"/api/transactions/{ident}", json=data).status_code == 404
    assert bob.delete(f"/api/transactions/{ident}").status_code == 404
    assert bob.post(f"/api/transactions/{ident}/restore").status_code == 404
    assert alice.get("/api/operations/health").status_code == 403
    assert bob.get("/api/auth/profile").json()["username"] == "bob"
    foreign_account = alice.get("/api/accounts").json()[0]["id"]
    data["account_id"] = foreign_account
    assert bob.post("/api/transactions", json=data).status_code == 404
    assert (
        bob.post("/api/transactions/import/preview", json={"rows": [data]}).json()["rows"][0]["status"]
        == "invalid"
    )


def test_session_controls_require_csrf_and_cannot_revoke_another_user(clients):
    _owner, _service, members = clients
    alice, _first = members[0]
    bob, _second = members[1]
    foreign = bob.get("/api/auth/sessions").json()[0]
    assert "token_hash" not in foreign and "csrf" not in foreign
    assert alice.delete("/api/auth/sessions/" + foreign["session_id"]).status_code == 404
    own = alice.get("/api/auth/sessions").json()[0]
    csrf = alice.headers.pop("X-CSRF-Token")
    assert alice.delete("/api/auth/sessions/" + own["session_id"]).status_code == 403
    alice.headers["X-CSRF-Token"] = csrf
    assert alice.delete("/api/auth/sessions/" + own["session_id"]).status_code == 204
    assert alice.get("/api/accounts").status_code == 401
    assert bob.get("/api/accounts").status_code == 200


def test_password_change_revokes_sessions_and_leaves_other_user_usable(clients):
    _owner, _service, members = clients
    alice, _first = members[0]
    bob, _second = members[1]
    payload = {"current_password": "wrong", "password": NEW_PASSWORD}
    assert alice.post("/api/auth/password", json=payload).status_code == 400
    assert alice.get("/api/auth/profile").status_code == 200
    payload["current_password"] = PASSWORD
    assert alice.post("/api/auth/password", json=payload).status_code == 204
    assert alice.get("/api/auth/profile").status_code == 401
    assert bob.get("/api/auth/profile").status_code == 200
    response = alice.post("/api/auth/login", json={"username": "alice@example.com", "password": NEW_PASSWORD})
    assert response.status_code == 200
    assert response.json()["username"] == "alice"


def test_secret_fields_are_redacted_and_privileged_registration_fields_rejected(clients):
    owner, service, members = clients
    token = service.issue_code("invite", "carol@example.com")
    payload = {
        "token": token,
        "username": "carol",
        "display_name": "Carol",
        "email": "carol@example.com",
        "phone": "+381641234567",
        "password": PASSWORD,
        "is_admin": True,
        "user_id": 1,
    }
    response = owner.post("/api/auth/register", json=payload)
    assert response.status_code == 422
    assert token not in response.text and PASSWORD not in response.text
    assert members[0][0].get("/api/auth/profile").json()["is_admin"] is False
    payload.pop("is_admin")
    payload.pop("user_id")
    payload["password"] = "short-secret"
    response = owner.post("/api/auth/register", json=payload)
    assert response.status_code == 422 and "short-secret" not in response.text
    for page in ("/register", "/reset-password"):
        response = owner.get(page)
        assert response.status_code == 200
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"


def test_manual_recovery_link_is_one_time_and_no_public_email_reset_exists(clients):
    owner, service, members = clients
    alice, _first = members[0]
    token = service.issue_code("reset", "alice")
    payload = {"token": token, "password": NEW_PASSWORD}
    assert owner.post("/api/auth/reset-password", json=payload).status_code == 204
    assert alice.get("/api/accounts").status_code == 401
    assert owner.post("/api/auth/reset-password", json=payload).status_code == 400
    assert owner.post("/api/auth/forgot-password", json={"email": "alice@example.com"}).status_code == 401


def test_profile_cannot_set_role_owner_or_verification_flags(clients):
    _owner, _service, members = clients
    alice, first = members[0]
    payload = {
        "display_name": "Alice",
        "email": "alice@example.com",
        "phone": "+381641234567",
        "current_password": PASSWORD,
        "is_admin": True,
        "id": 1,
        "email_verified_at": "now",
    }
    assert alice.put("/api/auth/profile", json=payload).status_code == 422
    profile = alice.get("/api/auth/profile").json()
    assert profile["id"] == first["user_id"] and profile["is_admin"] is False


def test_administrator_role_does_not_grant_cross_owner_financial_access(clients):
    from .conftest import login_client

    owner, _service, members = clients
    alice, _first = members[0]
    created = alice.post(
        "/api/transactions",
        json={
            "date": business_date.today().isoformat(),
            "type": "income",
            "category": "Salary",
            "amount": "12.34",
        },
    ).json()
    login_client(owner)
    assert owner.get("/api/auth/session").json()["is_admin"] is True
    assert owner.get("/api/operations/health").status_code == 200
    assert owner.get("/api/transactions").json()["total"] == 0
    assert owner.get(f"/api/transactions/{created['id']}/history").status_code == 404


@pytest.mark.parametrize("value", ["bad\x00name", "bad\ud800name"])
def test_invalid_unicode_credentials_are_validation_errors_not_database_failures(clients, value):
    import json

    owner, service, _members = clients

    def post(path, payload):
        return owner.post(
            path, content=json.dumps(payload, ensure_ascii=True), headers={"Content-Type": "application/json"}
        )

    response = post("/api/auth/login", {"username": value, "password": PASSWORD})
    assert response.status_code == 422
    token = service.issue_code("invite", "carol@example.com")
    payload = {
        "token": token,
        "username": "carol",
        "display_name": value,
        "email": "carol@example.com",
        "phone": "+381641234567",
        "password": PASSWORD,
    }
    assert post("/api/auth/register", payload).status_code == 422
    payload["display_name"] = "Carol"
    payload["token"] = "\ud800" * 43
    assert post("/api/auth/register", payload).status_code == 422
