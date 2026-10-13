"""Run a disposable authenticated benchmark, never against a supplied HTTP target."""

import argparse
import http.client
import json
import os
import platform
import secrets
import select
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

from .server import validate_database_url

ROOT = Path(__file__).resolve().parents[1]
READS = (
    "/api/dashboard?days=30",
    "/api/accounts",
    "/api/transactions?limit=100",
    "/api/transactions?type=expense&account_id=1&limit=100",
    "/api/reports/monthly?months=12",
)
TABLES = (
    "accounts",
    "transactions",
    "transfers",
    "budgets",
    "recurring_transactions",
    "recurring_occurrences",
    "transaction_audit",
)


def request(base, path, *, cookie="", csrf="", payload=None):
    parts = urlsplit(base)
    if (
        parts.scheme != "http"
        or parts.hostname != "127.0.0.1"
        or not parts.port
        or parts.username
        or parts.password
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Benchmark HTTP target must be its generated loopback server")
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    headers = {"Origin": base, "Cookie": cookie, "X-CSRF-Token": csrf, "Content-Type": "application/json"}
    try:
        connection.request(
            "POST" if payload is not None else "GET",
            path,
            body=json.dumps(payload) if payload is not None else None,
            headers=headers,
        )
        response = connection.getresponse()
        body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024 or response.status != 200:
            raise RuntimeError("Benchmark request failed or exceeded its response limit")
        return json.loads(body), dict(response.getheaders())
    finally:
        connection.close()


def wait_for_server(process):
    deadline = time.monotonic() + 180
    assert process.stdout is not None
    while process.poll() is None and time.monotonic() < deadline:
        if select.select([process.stdout], [], [], 0.2)[0]:
            line = process.stdout.readline().strip()
            if line.startswith("BENCH_URL="):
                base = line.removeprefix("BENCH_URL=")
                for _ in range(150):
                    try:
                        request(base, "/api/health/ready")
                        return base
                    except (OSError, RuntimeError):
                        if process.poll() is not None:
                            break
                        time.sleep(0.2)
                break
    raise RuntimeError("Disposable benchmark server did not become ready")


def snapshot(url):
    with psycopg.connect(url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return {
            table: connection.execute(
                sql.SQL(
                    "SELECT count(*), md5(COALESCE(string_agg(row_to_json(t)::text,'' "
                    "ORDER BY row_to_json(t)::text),'')) FROM {} t"
                ).format(sql.Identifier(table))
            ).fetchone()
            for table in TABLES
        }


def process_sample(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pcpu=,rss="], capture_output=True, text=True, check=True
    )
    cpu, rss = result.stdout.split()
    return {"cpu_percent_lifetime_average": float(cpu), "sampled_rss_mib": int(rss) / 1024}


def serial_profile(base, cookie, csrf):
    today = request(base, "/api/ledger-policy", cookie=cookie)[0]["business_date"]
    preview = {
        "rows": [
            {
                "date": today,
                "type": "expense",
                "category": "Preview",
                "amount": "12.34",
                "description": f"Preview {n}",
            }
            for n in range(1000)
        ]
    }
    results = {}
    for path, payload in [*((path, None) for path in READS), ("/api/transactions/import/preview", preview)]:
        request(base, path, cookie=cookie, csrf=csrf, payload=payload)
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            request(base, path, cookie=cookie, csrf=csrf, payload=payload)
            samples.append((time.perf_counter() - start) * 1000)
        results[path] = {"samples": 5, "median_ms": statistics.median(samples), "max_ms": max(samples)}
    return today, results


def benchmark(args):
    from backend.tests.postgres_helpers import temporary_schema

    url = validate_database_url(os.environ.get("BENCH_DATABASE_URL", "postgresql:///finance_dashboard_test"))
    k6 = shutil.which(args.k6)
    if k6 is None:
        raise FileNotFoundError("Install k6 or provide --k6 with its executable path")
    directory = Path(args.output).resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(3)
    )
    directory.mkdir(parents=True, mode=0o700)
    report = {
        "rows": args.rows,
        "pool_size": 5,
        "workers": 1,
        "reload": False,
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "phases": [],
        "authentication": "single-owner shared synthetic session",
        "financial_data_unchanged": None,
        "status": "incomplete",
    }
    report["git_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    report["working_tree_dirty"] = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    password = secrets.token_urlsafe(32)
    with temporary_schema(url) as isolated:
        env = {
            **os.environ,
            "BENCH_ISOLATED_URL": isolated,
            "BENCH_PASSWORD": password,
            "BENCH_ROWS": str(args.rows),
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "benchmarks.server"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            base = wait_for_server(process)
            with psycopg.connect(isolated) as connection:
                report["postgres_version"] = connection.info.server_version
            login, headers = request(
                base, "/api/auth/login", payload={"username": "owner", "password": password}
            )
            cookies = SimpleCookie(headers["set-cookie"])
            cookie = "finance_session=" + cookies["finance_session"].value
            before = snapshot(isolated)
            if before["transactions"][0] != args.rows:
                raise RuntimeError("Unexpected synthetic row count")
            report["business_date"], report["serial_operations"] = serial_profile(
                base, cookie, login["csrf_token"]
            )
            for rate in (1, 5, 10, 20):
                phase_path = directory / f"rate-{rate}.json"
                result = subprocess.run(
                    [
                        k6,
                        "run",
                        "--quiet",
                        "--config",
                        str(ROOT / "benchmarks/k6-config.json"),
                        str(ROOT / "benchmarks/read-load.js"),
                    ],
                    cwd=ROOT,
                    env={
                        **{key: value for key, value in os.environ.items() if not key.startswith("K6_")},
                        "K6_NO_USAGE_REPORT": "true",
                        "BENCH_BASE": base,
                        "BENCH_COOKIE": cookie,
                        "BENCH_RATE": str(rate),
                        "BENCH_SECONDS": str(args.seconds),
                        "BENCH_PHASE_REPORT": str(phase_path),
                    },
                    capture_output=True,
                    timeout=args.seconds + 45,
                )
                if result.returncode not in (0, 99) or not phase_path.exists():
                    raise RuntimeError("k6 did not complete its bounded phase")
                phase = json.loads(phase_path.read_text())
                if phase.get("requests", 0) <= 0 or "p(95)" not in phase.get("latency_ms", {}):
                    raise RuntimeError("k6 report is missing read request measurements")
                phase["thresholds_passed"] = result.returncode == 0
                phase["server"] = process_sample(process.pid)
                phase["pool"] = request(base, "/api/benchmark/pool", cookie=cookie)[0]
                report["phases"].append(phase)
                print(
                    f"{rate} RPS: {phase['requests']} requests, "
                    f"p95={phase['latency_ms'].get('p(95)', 0):.1f} ms, "
                    f"503={phase['capacity_503']}, dropped={phase['dropped_iterations']}",
                    flush=True,
                )
            report["financial_data_unchanged"] = snapshot(isolated) == before
            if not report["financial_data_unchanged"]:
                raise RuntimeError("Read-only benchmark changed financial data")
            report["status"] = "complete"
        finally:
            process.terminate()
            try:
                process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
            (directory / "summary.json").write_text(json.dumps(report, indent=2))
    print("Report: " + str(directory / "summary.json"))
    return 0 if all(phase["thresholds_passed"] for phase in report["phases"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100000)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--k6", default="k6")
    parser.add_argument("--output", default="benchmark-results")
    args = parser.parse_args()
    if not 1 <= args.rows <= 100000 or not 5 <= args.seconds <= 30:
        parser.error("Use 1..100000 rows and 5..30 seconds per phase")
    try:
        return benchmark(args)
    except KeyboardInterrupt:
        print("Benchmark interrupted.", file=sys.stderr)
        return 130
    except Exception as error:
        print(
            f"Benchmark failed ({type(error).__name__}); check local test DB and k6 setup.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
