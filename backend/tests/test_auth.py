import time
from types import SimpleNamespace

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
    assert 1 <= int(response.headers["retry-after"]) <= 60
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
    monkeypatch.setattr(settings, "cors_origins", "https://testserver")
    response = raw_client.post(
        "https://testserver/api/auth/login",
        headers={"Origin": "https://testserver"},
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
        allowed_hosts="example.com",
        trusted_proxy_ips="127.0.0.1",
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


def test_production_rejects_plaintext_even_with_spoofed_proxy_header(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    response = raw_client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver", "X-Forwarded-Proto": "https"},
        json={"username": "owner", "password": TEST_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "HTTPS required"


def test_content_security_policy_is_report_only(raw_client):
    response = raw_client.get("/login")
    assert "script-src 'self'" in response.headers["content-security-policy-report-only"]
    assert "content-security-policy" not in response.headers


def test_source_limit_does_not_lock_out_another_source(raw_client, monkeypatch):
    from app.services import auth_service
    from fastapi import HTTPException

    service = AuthService(app.state.database)
    monkeypatch.setattr(auth_service, "PASSWORDS", SimpleNamespace(verify=lambda *args: False))
    for _ in range(10):
        with pytest.raises(HTTPException) as error:
            service.login("wrong", "wrong", None, "192.0.2.1")
        assert error.value.status_code == 401
    with pytest.raises(HTTPException) as error:
        service.login("owner", TEST_PASSWORD, None, "192.0.2.1")
    assert error.value.status_code == 429
    monkeypatch.setattr(auth_service, "PASSWORDS", SimpleNamespace(verify=lambda *args: True))
    token, _ = service.login("owner", TEST_PASSWORD, None, "192.0.2.2")
    assert service.session(token) is not None


def test_forwarded_address_cannot_reset_source_limit(raw_client, monkeypatch):
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "PASSWORDS", SimpleNamespace(verify=lambda *args: False))
    for index in range(11):
        response = raw_client.post(
            "/api/auth/login",
            headers={"Origin": "http://testserver", "X-Forwarded-For": f"192.0.2.{index}"},
            json={"username": "wrong", "password": "wrong"},
        )
        assert response.status_code == (401 if index < 10 else 429)


def test_global_limit_and_remaining_retry_time(raw_client, monkeypatch):
    from app.services import auth_service
    from fastapi import HTTPException

    now = int(time.time())
    monkeypatch.setattr(auth_service.time, "time", lambda: now)
    with app.state.database.operational_transaction() as conn:
        conn.execute("UPDATE auth_login_limit SET window_start=?,attempts=100", (now - 20,))
    with pytest.raises(HTTPException) as error:
        AuthService(app.state.database).login("owner", TEST_PASSWORD, None, "new-source")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "40"


def test_session_activity_is_throttled_and_expiry_stays_bounded(raw_client, monkeypatch):
    from app.services import auth_service

    login_client(raw_client)
    token = raw_client.cookies.get(COOKIE)
    service = AuthService(app.state.database)
    with app.state.database.connection() as conn:
        initial = conn.execute("SELECT last_seen FROM auth_sessions").fetchone()[0]
    monkeypatch.setattr(auth_service.time, "time", lambda: initial + 59)
    assert service.session(token) is not None
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT last_seen FROM auth_sessions").fetchone()[0] == initial
    monkeypatch.setattr(auth_service.time, "time", lambda: initial + 60)
    assert service.session(token) is not None
    with app.state.database.connection() as conn:
        assert conn.execute("SELECT last_seen FROM auth_sessions").fetchone()[0] == initial + 60
    monkeypatch.setattr(auth_service.time, "time", lambda: initial + 60 + settings.session_idle_seconds)
    assert service.session(token) is None


def test_concurrent_dashboard_reads_do_not_wait_for_financial_writer(raw_client):
    from concurrent.futures import ThreadPoolExecutor

    login_client(raw_client)
    with app.state.database.connection() as writer, writer:
        writer.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=20) as workers:
            futures = [workers.submit(raw_client.get, "/api/dashboard") for _ in range(50)]
            for future in futures:
                assert future.result(timeout=10).status_code == 200


def test_due_activity_touch_does_not_wait_for_financial_writer(raw_client, monkeypatch):
    from app.services import auth_service

    login_client(raw_client)
    token = raw_client.cookies.get(COOKIE)
    with app.state.database.connection() as conn:
        initial = conn.execute("SELECT last_seen FROM auth_sessions").fetchone()[0]
    monkeypatch.setattr(auth_service.time, "time", lambda: initial + 61)
    with app.state.database.connection() as writer, writer:
        writer.execute("BEGIN IMMEDIATE")
        assert AuthService(app.state.database).session(token) is not None
    AuthService(app.state.database).logout(token)
    assert AuthService(app.state.database).session(token) is None


def test_hashing_concurrency_has_a_bounded_capacity(raw_client, monkeypatch):
    from threading import BoundedSemaphore

    from app.services import auth_service
    from fastapi import HTTPException

    slots = BoundedSemaphore(1)
    monkeypatch.setattr(auth_service, "HASH_SLOTS", slots)
    slots.acquire()
    try:
        with pytest.raises(HTTPException) as error:
            AuthService(app.state.database).login("owner", TEST_PASSWORD, None)
        assert error.value.status_code == 429
        assert error.value.headers["Retry-After"] == "1"
    finally:
        slots.release()
    token, _ = AuthService(app.state.database).login("owner", TEST_PASSWORD, None)
    assert AuthService(app.state.database).session(token) is not None
