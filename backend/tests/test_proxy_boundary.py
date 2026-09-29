import asyncio

import pytest
from app.core.config import Settings, settings
from app.main import app
from app.serve import main, server_options
from fastapi.testclient import TestClient
from pydantic import ValidationError
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


def production(**changes):
    return Settings(
        _env_file=None,
        **{
            "environment": "production",
            "owner_password_hash": "synthetic-hash",
            "cors_origins": "https://finance.example.com",
            "allowed_hosts": "finance.example.com",
            "trusted_proxy_ips": "127.0.0.1",
            **changes,
        },
    )


@pytest.mark.parametrize(
    "value",
    ["*", "0.0.0.0/0", "127.0.0.0/8", "localhost", "0.0.0.0", "::", "ff02::1", "127.0.0.1,", "fe80::1%lo"],
)
def test_reject_overbroad_or_ambiguous_proxy_trust(value):
    with pytest.raises(ValidationError):
        production(trusted_proxy_ips=value)


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "*.example.com",
        "https://example.com",
        "example.com:443",
        "example.com/path",
        "example.com@evil",
        "",
        "example.com,",
        "-bad",
    ],
)
def test_reject_invalid_hostname_allowlist(value):
    with pytest.raises(ValidationError):
        production(allowed_hosts=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"trusted_proxy_ips": ""},
        {"allowed_hosts": "another.example.com"},
        {"cors_origins": "https://finance.example.com,https://another.example.com"},
        {"owner_password_hash": None},
        {"cors_origins": "http://finance.example.com"},
    ],
)
def test_production_configuration_fails_closed(changes):
    with pytest.raises(ValidationError):
        production(**changes)


def test_production_launcher_has_explicit_private_boundary(monkeypatch):
    config = production()
    options = server_options(config)
    assert options["host"] == "127.0.0.1"
    assert options["proxy_headers"] is True
    assert options["forwarded_allow_ips"] == "127.0.0.1"
    assert options["reload"] is False
    assert options["access_log"] is False
    assert options["workers"] == 1
    with pytest.raises(ValueError, match="production"):
        server_options(Settings(_env_file=None))
    config.trusted_proxy_ips = "*"
    with pytest.raises(ValidationError):
        server_options(config)
    import app.serve as serve

    captured = {}
    monkeypatch.setattr(serve, "settings", production())
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: captured.update(kw))
    main()
    assert captured["forwarded_allow_ips"] == "127.0.0.1"


def test_host_rejection_precedes_authentication(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", "finance.example.com")
    client = TestClient(app)  # No lifespan/database needed for rejection.
    response = client.get("http://evil.example/api/accounts")
    assert response.status_code == 400
    assert "Invalid host" in response.text


@pytest.mark.parametrize(
    "peer,expected_scheme,expected_ip",
    [
        ("127.0.0.1", "https", "198.51.100.4"),
        ("127.0.0.2", "http", "127.0.0.2"),
    ],
)
def test_installed_uvicorn_honors_only_exact_peer(peer, expected_scheme, expected_ip):
    captured = {}

    async def target(scope, receive, send):
        captured.update(scope)

    middleware = ProxyHeadersMiddleware(target, trusted_hosts="127.0.0.1")
    scope = {
        "type": "http",
        "scheme": "http",
        "client": (peer, 1234),
        "headers": [(b"x-forwarded-proto", b"https"), (b"x-forwarded-for", b"198.51.100.4")],
    }
    asyncio.run(middleware(scope, None, None))
    assert captured["scheme"] == expected_scheme
    assert captured["client"][0] == expected_ip
