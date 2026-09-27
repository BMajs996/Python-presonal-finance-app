import time

import pytest
from app.core.config import Settings, settings
from app.main import app
from app.services.auth_service import COOKIE, AuthService, token_hash
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from .conftest import TEST_PASSWORD, login_client
from .postgres_helpers import pg_url as pg_url


@pytest.fixture(params=["sqlite", "postgres"])
def raw_client(request, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "auth.db")
    if request.param == "postgres":
        monkeypatch.setattr(settings, "database_url", SecretStr(request.getfixturevalue("pg_url")))
    with TestClient(app) as client:
        yield client


def test_all_financial_routes_require_owner(raw_client):
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/") or path == "/api/health" or path.startswith("/api/auth/"):
            continue
        for method in operations:
            if method.upper() not in {"GET", "POST", "PUT", "DELETE"}:
                continue
            checked += 1
            response = raw_client.request(method, path, headers={"Origin": "http://testserver"})
            assert response.status_code == 401, (path, method, response.text)
    assert checked >= 20
    assert raw_client.get("/openapi.json").status_code == 401
    assert raw_client.get("/docs").status_code == 401
    assert raw_client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert raw_client.get("/login").status_code == 200
    assert raw_client.get("/api/health").status_code == 200


def test_login_csrf_logout_and_replay(raw_client):
    login_client(raw_client)
    token = raw_client.cookies.get(COOKIE)
    session = raw_client.get("/api/auth/session")
    assert session.status_code == 200
    assert session.headers["cache-control"] == "no-store"
    with app.state.database.connection() as conn:
        row = conn.execute("SELECT * FROM auth_sessions").fetchone()
        assert row["token_hash"] == token_hash(token)
        assert row["token_hash"] != token

    payload = {"name": "Protected account"}
    csrf = raw_client.headers.pop("X-CSRF-Token")
    assert raw_client.post("/api/accounts", json=payload).status_code == 403
    assert (
        raw_client.post("/api/accounts", json=payload, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    )
    raw_client.headers["X-CSRF-Token"] = csrf
    assert (
        raw_client.post("/api/accounts", json=payload, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert raw_client.post("/api/accounts", json=payload).status_code == 201
    assert raw_client.post("/api/auth/logout").status_code == 204
    assert raw_client.get("/api/accounts").status_code == 401
    raw_client.cookies.set(COOKIE, token)
    assert raw_client.get("/api/accounts").status_code == 401


def test_origin_checks_and_cors_preflight(raw_client):
    payload = {"username": "owner", "password": TEST_PASSWORD}
    assert raw_client.post("/api/auth/login", json=payload).status_code == 403
    assert raw_client.post("/api/auth/login", json=payload, headers={"Origin": "null"}).status_code == 403
    headers = {
        "Origin": "http://testserver",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-csrf-token",
    }
    response = raw_client.options("/api/accounts", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert response.headers["access-control-allow-credentials"] == "true"
    for changed in (
        {"Origin": "https://evil.example"},
        {"Access-Control-Request-Method": "PATCH"},
        {"Access-Control-Request-Headers": "X-Arbitrary"},
    ):
        assert raw_client.options("/api/accounts", headers={**headers, **changed}).status_code == 400
    rejected = raw_client.get("/api/accounts", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in rejected.headers
    allowed = raw_client.get("/api/accounts", headers={"Origin": "http://testserver"})
    assert allowed.status_code == 401
    assert allowed.headers["access-control-allow-origin"] == "http://testserver"


def test_expiry_and_password_rotation(raw_client, monkeypatch):
    login_client(raw_client)
    with app.state.database.connection() as conn, conn:
        conn.execute("UPDATE auth_sessions SET last_seen=?", (int(time.time()) - 3600,))
    assert raw_client.get("/api/auth/session").status_code == 401
    login_client(raw_client)
    with app.state.database.connection() as conn, conn:
        conn.execute("UPDATE auth_sessions SET expires_at=0")
    assert raw_client.get("/api/accounts").status_code == 401
    login_client(raw_client)
    monkeypatch.setattr(settings, "owner_password_hash", SecretStr("changed"))
    assert raw_client.get("/api/accounts").status_code == 401


def test_session_rotation_and_worker_persistence(raw_client):
    login_client(raw_client)
    old = raw_client.cookies.get(COOKIE)
    login_client(raw_client)
    current = raw_client.cookies.get(COOKIE)
    assert old != current
    another_worker = AuthService(app.state.database)
    assert another_worker.session(old) is None
    assert another_worker.session(current) is not None
    assert another_worker.session("x" * 129) is None


def test_bad_credentials_throttle_and_window_reset(raw_client, monkeypatch):
    from app.services import auth_service

    payload = {"username": "wrong", "password": "wrong"}
    headers = {"Origin": "http://testserver"}
    for _ in range(10):
        response = raw_client.post("/api/auth/login", json=payload, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid username or password"}
    response = raw_client.post("/api/auth/login", json=payload, headers=headers)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    future = time.time() + 61
    monkeypatch.setattr(auth_service.time, "time", lambda: future)
    login_client(raw_client)


def test_unconfigured_owner_and_password_redaction(raw_client, monkeypatch):
    response = raw_client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": "secret-marker" * 100},
    )
    assert response.status_code == 422
    assert "secret-marker" not in response.text
    monkeypatch.setattr(settings, "owner_password_hash", None)
    response = raw_client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": TEST_PASSWORD},
    )
    assert response.status_code == 503
    assert raw_client.get("/api/accounts").status_code == 401


def test_cookie_attributes(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    response = raw_client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/", "max-age="):
        assert attribute in cookie
    assert "domain=" not in cookie


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "null",
        "",
        "https://*.example.com",
        "https://example.com/path",
        "https://user:password@example.com",
        "https://example.com?x=y",
    ],
)
def test_reject_unsafe_origin_settings(origin):
    with pytest.raises(ValidationError):
        Settings(cors_origins=origin, _env_file=None)


def test_production_requires_https_and_owner():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            cors_origins="http://example.com",
            owner_password_hash="test",
            _env_file=None,
        )
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            cors_origins="https://example.com",
            owner_password_hash=None,
            _env_file=None,
        )
    configured = Settings(
        environment="production",
        cors_origins="https://example.com",
        owner_password_hash="test",
        _env_file=None,
    )
    assert configured.secure_cookies


def test_owner_setup_preserves_configuration(tmp_path, monkeypatch, capsys):
    from app import setup_owner
    from dotenv import dotenv_values

    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=postgresql:///example\n")
    monkeypatch.setattr(setup_owner, "getpass", lambda prompt: TEST_PASSWORD)
    setup_owner.main()
    values = dotenv_values(path)
    assert values["DATABASE_URL"] == "postgresql:///example"
    assert setup_owner.PASSWORDS.verify(values["OWNER_PASSWORD_HASH"], TEST_PASSWORD)
    assert path.stat().st_mode & 0o777 == 0o600
    assert TEST_PASSWORD not in capsys.readouterr().out


@pytest.mark.parametrize("answers", [("short",), (TEST_PASSWORD, "different")])
def test_owner_setup_rejects_invalid_password(tmp_path, monkeypatch, answers):
    from app import setup_owner

    monkeypatch.chdir(tmp_path)
    replies = iter(answers)
    monkeypatch.setattr(setup_owner, "getpass", lambda prompt: next(replies))
    with pytest.raises(SystemExit):
        setup_owner.main()
    assert not (tmp_path / ".env").exists()


def test_frontend_assets_always_revalidate(raw_client):
    for path in ("/assets/app.js", "/assets/api/client.js", "/assets/styles.css"):
        response = raw_client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        cached = raw_client.get(path, headers={"If-None-Match": response.headers["etag"]})
        assert cached.status_code == 304
        assert cached.headers["cache-control"] == "no-cache"


def test_pages_reference_versioned_module_graph(raw_client):
    from app.main import asset_revision

    prefix = f"/assets/{asset_revision}/"
    assert prefix + "login.js" in raw_client.get("/login").text
    login_client(raw_client)
    page = raw_client.get("/")
    assert prefix + "app.js" in page.text
    assert 'src="/assets/app.js"' not in page.text
    for name in ("app.js", "api/client.js", "views/dashboard.js", "styles.css", "vendor/chart.umd.js"):
        response = raw_client.get(prefix + name)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"


def test_frontend_revision_changes_with_imported_modules(tmp_path):
    from app.frontend_assets import frontend_revision

    (tmp_path / "app.js").write_text('import "./client.js";')
    client = tmp_path / "client.js"
    client.write_text("export const version = 1;")
    first = frontend_revision(tmp_path)
    assert first == frontend_revision(tmp_path)
    client.write_text("export const version = 2;")
    assert first != frontend_revision(tmp_path)
