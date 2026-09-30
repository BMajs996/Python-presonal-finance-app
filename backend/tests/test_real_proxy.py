"""Real TLS proxy boundary tests; no live database, DNS or firewall changes."""

import hashlib
import json
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
from uuid import uuid4

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
    # Test-only log contains no request bodies, credentials or query strings.
    template = template.replace("access_log off;", f"access_log {tmp_path}/boundary.log boundary;")
    config = tmp_path / "nginx.conf"
    config.write_text(f"""
        daemon off;
        master_process off;
        pid {tmp_path}/nginx.pid;
        error_log {tmp_path}/error.log warn;
        events {{ worker_connections 64; }}
        http {{
            log_format boundary '$status $upstream_addr';
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
            "tls_context": context,
            "https_port": https_port,
            "boundary_log": tmp_path / "boundary.log",
            "pids": (app_process.pid, proxy_process.pid),
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


def wire_request(stack, path, body=None, *, declared_length=None, stall=False, credentials=None):
    """Send raw TLS requests so tests control framing and incomplete uploads."""
    with socket.create_connection(("127.0.0.1", stack["https_port"]), timeout=25) as transport:
        with stack["tls_context"].wrap_socket(transport, server_hostname="localhost") as conn:
            headers = (
                f"POST {path} HTTP/1.1\r\nHost: localhost:{stack['https_port']}\r\n"
                f"Origin: {stack['origin']}\r\nContent-Type: application/json\r\n"
                "Connection: close\r\n"
            )
            if credentials:
                headers += f"Cookie: {credentials[0]}\r\nX-CSRF-Token: {credentials[1]}\r\n"
            if declared_length is not None:
                conn.sendall(
                    (headers + f"Content-Length: {declared_length}\r\nExpect: 100-continue\r\n\r\n").encode()
                )
            else:
                conn.sendall((headers + "Transfer-Encoding: chunked\r\n\r\n").encode())
                if stall:
                    # Begin a chunk without finishing it or ending the request.
                    conn.sendall(b"10\r\n{")
                else:
                    for offset in range(0, len(body), 16384):
                        chunk = body[offset : offset + 16384]
                        conn.sendall(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                    conn.sendall(b"0\r\n\r\n")
            response = b""
            while b"\r\n" not in response:
                part = conn.recv(4096)
                if not part:
                    break
                response += part
            return response.split(b"\r\n", 1)[0]


def transaction_count(stack):
    if stack["url"]:
        with psycopg.connect(stack["url"]) as conn:
            return conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
    with closing(sqlite3.connect(stack["db"])) as conn:
        return conn.execute("SELECT count(*) FROM transactions").fetchone()[0]


def rss_kib(pid):
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return None
    return int(next(line.split()[1] for line in status.read_text().splitlines() if line.startswith("VmRSS:")))


def assert_edge_only(stack, previous_log):
    lines = stack["boundary_log"].read_text()[len(previous_log) :].splitlines()
    assert lines
    assert all(line.split()[-1] == "-" for line in lines), lines


def test_oversized_requests_stop_before_authentication_or_financial_writes(proxy_stack):
    stack = proxy_stack
    login = json.dumps({"username": "owner", "password": TEST_PASSWORD}).encode()
    csv = json.dumps(
        {
            "batch_id": str(uuid4()),
            "rows": [{"date": "2020-01-01", "type": "income", "amount": "1.00", "category": "Test"}],
        }
    ).encode()
    before_log = stack["boundary_log"].read_text()
    before_auth, before_rows = counters(stack), transaction_count(stack)
    before_memory = [rss_kib(pid) for pid in stack["pids"]]
    # Query strings, trailing slashes and URL decoding must not bypass the small login cap.
    routes = [
        ("/api/auth/login", 16 * 1024, login),
        ("/api/auth/login/?next=x", 16 * 1024, login),
        ("/api/auth/%6cogin", 16 * 1024, login),
        ("/api/transactions/import", 8 * 1024 * 1024, csv),
        ("/api/transactions/import/preview", 8 * 1024 * 1024, csv),
        ("/api/transactions/import/preview/", 8 * 1024 * 1024, csv),
        ("/api/accounts", 2 * 1024 * 1024, csv),
        ("/api/transactions/import/other", 2 * 1024 * 1024, csv),
    ]
    for path, limit, payload in routes:
        assert b" 413 " in wire_request(stack, path, declared_length=limit + 1)
        # Valid JSON with legal whitespace would reach application work without the edge cap.
        assert b" 413 " in wire_request(stack, path, payload + b" " * (limit + 1 - len(payload)))
    assert counters(stack) == before_auth
    assert transaction_count(stack) == before_rows
    assert_edge_only(stack, before_log)
    for pid, baseline in zip(stack["pids"], before_memory, strict=True):
        if baseline is not None:
            # A coarse regression guard, not an assertion about total capacity under load.
            assert rss_kib(pid) - baseline < 16 * 1024

    # Authenticated CSV requests must be rejected just as early.
    client = stack["clients"]["127.0.0.2"]
    signed_in = client.post("/api/auth/login", json={"username": "owner", "password": TEST_PASSWORD})
    assert signed_in.status_code == 200
    credentials = (
        "; ".join(f"{key}={value}" for key, value in client.cookies.items()),
        signed_in.json()["csrf_token"],
    )
    before_log, before_auth = stack["boundary_log"].read_text(), counters(stack)
    for path in ("/api/transactions/import", "/api/transactions/import/preview"):
        assert b" 413 " in wire_request(
            stack, path, declared_length=8 * 1024 * 1024 + 1, credentials=credentials
        )
        assert b" 413 " in wire_request(
            stack, path, csv + b" " * (8 * 1024 * 1024 + 1 - len(csv)), credentials=credentials
        )
    assert counters(stack) == before_auth
    assert transaction_count(stack) == before_rows
    assert_edge_only(stack, before_log)


def test_incomplete_bodies_timeout_before_reaching_application(proxy_stack):
    stack = proxy_stack
    before_log = stack["boundary_log"].read_text()
    before_auth, before_rows = counters(stack), transaction_count(stack)
    for path, timeout in (("/api/auth/login", 5), ("/api/transactions/import", 15)):
        started = time.monotonic()
        response = wire_request(stack, path, stall=True)
        assert response == b"" or b" 408 " in response
        assert timeout - 0.5 <= time.monotonic() - started < 24
    assert stack["boundary_log"].read_text()[len(before_log) :].splitlines() == ["408 -", "408 -"]
    assert counters(stack) == before_auth
    assert transaction_count(stack) == before_rows
    assert_edge_only(stack, before_log)


def test_maximum_length_unicode_csv_batch_fits_proxy_limit(proxy_stack):
    stack = proxy_stack
    client = stack["clients"]["127.0.0.2"]
    login = client.post("/api/auth/login", json={"username": "owner", "password": TEST_PASSWORD})
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    # Non-BMP code points occupy 12 bytes each in ASCII-escaped JSON.
    symbol = chr(0x1F600)
    rows = [
        {
            "date": "2020-01-01",
            "type": "income",
            "amount": "0.01",
            "category": symbol * 100,
            "description": symbol * 499 + chr(0x20000 + index),
        }
        for index in range(1000)
    ]
    body = json.dumps({"rows": rows, "batch_id": str(uuid4())}, ensure_ascii=True).encode()
    assert 7_000_000 < len(body) < 8 * 1024 * 1024
    headers = {"Content-Type": "application/json"}
    with httpx.Client(
        transport=httpx.HTTPTransport(verify=stack["tls_context"], local_address="127.0.0.2"),
        base_url=stack["origin"],
        cookies=client.cookies,
        headers={**dict(client.headers), **headers},
        timeout=60,
        trust_env=False,
    ) as uploader:
        preview = uploader.post(
            "/api/transactions/import/preview",
            content=(body[offset : offset + 16384] for offset in range(0, len(body), 16384)),
        )
        assert preview.status_code == 200, preview.text[:300]
        assert len(preview.json()["rows"]) == 1000
        assert all(row["status"] == "valid" for row in preview.json()["rows"])
        before = transaction_count(stack)
        committed = uploader.post("/api/transactions/import", content=body)
        assert committed.status_code == 200, committed.text[:300]
        assert committed.json() == {"imported": 1000, "duplicates": 0}
        assert transaction_count(stack) == before + 1000
        retried = uploader.post(
            "/api/transactions/import", content=json.dumps(json.loads(body), ensure_ascii=False).encode()
        )
        assert retried.json() == committed.json()
        assert transaction_count(stack) == before + 1000


def test_login_limit_allows_maximum_fields_and_exact_byte_boundary(proxy_stack):
    stack = proxy_stack
    # The schema counts characters, whereas the edge counts serialized bytes.
    symbol = chr(0x1F600)
    maximum = json.dumps({"username": symbol * 100, "password": symbol * 1024}, ensure_ascii=True).encode()
    assert 13_000 < len(maximum) < 16 * 1024
    assert b" 401 " in wire_request(stack, "/api/auth/login", maximum)
    valid = json.dumps({"username": "owner", "password": TEST_PASSWORD}).encode()
    assert b" 200 " in wire_request(stack, "/api/auth/login", valid + b" " * (16 * 1024 - len(valid)))
    assert sum(counters(stack).values()) == 2
