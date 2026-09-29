"""Real TLS proxy boundary tests; no live database, DNS or firewall changes."""

import hashlib
import os
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from contextlib import ExitStack, closing
from pathlib import Path

import httpx
import psycopg
import pytest

from .conftest import TEST_OWNER_HASH, TEST_PASSWORD
from .postgres_helpers import pg_url as pg_url

ROOT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture(params=["sqlite", "postgres"])
def proxy_stack(request, tmp_path):
    nginx = os.environ.get("NGINX_BINARY") or shutil.which("nginx")
    if not nginx:
        if os.environ.get("REQUIRE_PROXY_TESTS") == "1":
            pytest.fail("Nginx is required for proxy boundary tests")
        pytest.skip("Set NGINX_BINARY or install nginx to run real proxy tests")
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    app_port, http_port, https_port = free_port(), free_port(), free_port()
    cert, key = tmp_path / "certificate.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    origin = f"https://localhost:{https_port}"
    env = {
        **os.environ,
        "ENVIRONMENT": "production",
        "ALLOWED_HOSTS": "localhost",
        "CORS_ORIGINS": origin,
        "TRUSTED_PROXY_IPS": "127.0.0.1",
        "APP_PORT": str(app_port),
        "OWNER_USERNAME": "owner",
        "OWNER_PASSWORD_HASH": TEST_OWNER_HASH,
        "DATABASE_URL": url,
        "DATABASE_PATH": str(tmp_path / "isolated.db"),
        "BASE_CURRENCY": "USD",
        "BUSINESS_TIMEZONE": "Europe/Belgrade",
    }
    template = (ROOT / "deploy/nginx.conf.template").read_text()
    values = {
        "HTTP_LISTEN": f"127.0.0.1:{http_port}",
        "HTTPS_LISTEN": f"127.0.0.1:{https_port}",
        "DOMAIN": "localhost",
        "PUBLIC_AUTHORITY": f"localhost:{https_port}",
        "APP_PORT": str(app_port),
        "CERTIFICATE": str(cert),
        "CERTIFICATE_KEY": str(key),
    }
    for name, value in values.items():
        template = template.replace("@@" + name + "@@", value)
    assert "@@" not in template
    config = tmp_path / "nginx.conf"
    config.write_text(f"""
        daemon off;
        master_process off;
        pid {tmp_path}/nginx.pid;
        error_log {tmp_path}/error.log warn;
        events {{ worker_connections 64; }}
        http {{
            access_log off;
            client_body_temp_path {tmp_path}/body;
            proxy_temp_path {tmp_path}/proxy;
            fastcgi_temp_path {tmp_path}/fastcgi;
            uwsgi_temp_path {tmp_path}/uwsgi;
            scgi_temp_path {tmp_path}/scgi;
            {template}
        }}
    """)
    with ExitStack() as stack:
        app_log = stack.enter_context((tmp_path / "app.log").open("w"))
        app_process = subprocess.Popen(
            [sys.executable, "-m", "backend.app.serve"], cwd=ROOT, env=env, stdout=app_log, stderr=app_log
        )
        stack.callback(stop, app_process)
        subprocess.run([nginx, "-p", str(tmp_path), "-c", str(config), "-t"], check=True, capture_output=True)
        proxy_log = stack.enter_context((tmp_path / "proxy.log").open("w"))
        proxy_process = subprocess.Popen(
            [nginx, "-p", str(tmp_path), "-c", str(config)], stdout=proxy_log, stderr=proxy_log
        )
        stack.callback(stop, proxy_process)
        context = ssl.create_default_context(cafile=str(cert))
        clients = {}
        for source in ("127.0.0.2", "127.0.0.3"):
            client = httpx.Client(
                transport=httpx.HTTPTransport(verify=context, local_address=source),
                base_url=origin,
                headers={"Origin": origin},
                timeout=5,
                trust_env=False,
            )
            clients[source] = stack.enter_context(client)
        deadline = time.monotonic() + 15
        while True:
            assert app_process.poll() is None, (tmp_path / "app.log").read_text()
            assert proxy_process.poll() is None, (tmp_path / "error.log").read_text()
            try:
                if clients["127.0.0.2"].get("/api/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                pytest.fail("Isolated proxy startup timed out")
            time.sleep(0.1)
        yield {
            "clients": clients,
            "http": f"http://localhost:{http_port}",
            "origin": origin,
            "app_port": app_port,
            "db": tmp_path / "isolated.db",
            "url": url,
        }


def counters(stack):
    if stack["url"]:
        with psycopg.connect(stack["url"]) as conn:
            return dict(conn.execute("SELECT source_key,attempts FROM auth_source_limits").fetchall())
    with closing(sqlite3.connect(stack["db"])) as conn:
        return dict(conn.execute("SELECT source_key,attempts FROM auth_source_limits").fetchall())


def test_real_tls_proxy_authentication_and_spoof_resistance(proxy_stack):
    stack = proxy_stack
    first, second = stack["clients"].values()
    before = counters(stack)
    with httpx.Client(trust_env=False, follow_redirects=False) as plain:
        redirect = plain.get(stack["http"] + "/login")
        assert redirect.status_code == 308
        assert redirect.headers["location"] == stack["origin"] + "/login"
        assert (
            plain.post(
                stack["http"] + "/api/auth/login", json={"username": "owner", "password": "synthetic-only"}
            ).status_code
            == 400
        )
        assert plain.get(stack["http"] + "/", headers={"Host": "evil.example"}).status_code == 400
    assert counters(stack) == before
    assert first.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert "strict-transport-security" not in first.get("/login").headers
    assert first.get("/api/health", headers={"X-Forwarded-Proto": "http"}).status_code == 200

    forged = [
        ("X-Forwarded-Proto", "http"),
        ("X-Forwarded-Proto", "https"),
        ("X-Forwarded-For", "198.51.100.5"),
        ("X-Forwarded-For", "203.0.113.7, 127.0.0.1"),
        ("Forwarded", "for=198.51.100.6;proto=http;host=evil.example"),
        ("X-Real-IP", "198.51.100.8"),
        ("X-Forwarded-Host", "evil.example"),
    ]
    for _attempt in range(10):
        response = first.post(
            "/api/auth/login", headers=forged, json={"username": "owner", "password": "wrong"}
        )
        assert response.status_code == 401, response.text
    assert (
        first.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": "192.0.2.99"},
            json={"username": "owner", "password": TEST_PASSWORD},
        ).status_code
        == 429
    )
    source_key = hashlib.sha256(b"127.0.0.2").hexdigest()
    assert counters(stack) == {source_key: 10}
    login = second.post(
        "/api/auth/login", headers=forged, json={"username": "owner", "password": TEST_PASSWORD}
    )
    assert login.status_code == 200, login.text
    cookie = login.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("secure", "httponly", "samesite=strict", "path=/"))
    assert second.get("/").status_code == 200
    assert second.get("/api/auth/session").status_code == 200
    assert second.post("/api/accounts", json={"name": "Blocked without CSRF"}).status_code == 403
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert (
        second.post(
            "/api/accounts",
            headers={**csrf, "Origin": "https://evil.example"},
            json={"name": "Blocked origin"},
        ).status_code
        == 403
    )
    assert second.post("/api/accounts", headers=csrf, json={"name": "TLS account"}).status_code == 201
    assert second.post("/api/auth/logout", headers=csrf).status_code == 204
    assert second.get("/api/auth/session").status_code == 401

    # An untrusted loopback peer must not promote plaintext to HTTPS.
    with httpx.Client(transport=httpx.HTTPTransport(local_address="127.0.0.2"), trust_env=False) as direct:
        response = direct.get(
            f"http://127.0.0.1:{stack['app_port']}/api/health",
            headers={"Host": "localhost", "X-Forwarded-Proto": "https", "X-Forwarded-For": "192.0.2.10"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "HTTPS required"
