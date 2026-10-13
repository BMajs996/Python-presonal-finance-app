"""Seed and serve only an explicitly isolated local test schema."""

import os
import re
import socket
from urllib.parse import parse_qsl, urlsplit

import uvicorn
from argon2 import PasswordHasher


def validate_database_url(url: str, *, isolated: bool = False) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"postgresql", "postgres"}
        or parts.hostname not in {None, "localhost", "127.0.0.1", "::1"}
        or not parts.path.endswith("_test")
        or parts.fragment
        or any(key in {"host", "hostaddr", "dbname", "service"} for key, _ in parse_qsl(parts.query))
    ):
        raise ValueError("Benchmark requires a local PostgreSQL database ending in _test")
    if isolated:
        options = dict(parse_qsl(parts.query)).get("options", "")
        if re.fullmatch(r"-csearch_path=test_[0-9a-f]{32}", options) is None:
            raise ValueError("Benchmark server requires a generated isolated schema")
    return url


def seed(database, rows: int, today):
    if not 1 <= rows <= 100000:
        raise ValueError("Synthetic row count must be between 1 and 100000")
    validate_database_url(database._url, isolated=True)
    with database.conn.raw.transaction():
        if database.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] or (
            database.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] != 1
        ):
            raise ValueError("Benchmark seed requires a fresh isolated database")
        database.conn.execute(
            "INSERT INTO accounts(id,name,type,currency,created_at,active) "
            "SELECT n,'Synthetic ' || n,'checking','USD',?,CASE WHEN n<=10 THEN 1 ELSE 0 END "
            "FROM generate_series(2,100) n",
            (today.isoformat(),),
        )
        database.conn.execute(
            """INSERT INTO transactions(date,type,category,amount,amount_cents,description,account_id)
            SELECT to_char(?::date-mod(n,730)::integer,'YYYY-MM-DD'),
                   CASE WHEN mod(n,7)=0 THEN 'income' ELSE 'expense' END,
                   'Category ' || mod(n,5), (100+mod(n,100000))/100.0,
                   100+mod(n,100000), 'Synthetic entry ' || n, 1+mod(n,100)
            FROM generate_series(1,?) n""",
            (today.isoformat(), rows),
        )
        database.conn.execute(
            """INSERT INTO transfers(date,from_account_id,to_account_id,amount,amount_cents,created_at)
            SELECT ?,1+mod(n,9),2+mod(n,9),25,2500,? FROM generate_series(1,1000) n""",
            (today.isoformat(), today.isoformat()),
        )
        database.conn.execute(
            """INSERT INTO budgets(category,monthly_limit,monthly_limit_cents,month_year)
            SELECT 'Category ' || n,500,50000,? FROM generate_series(0,4) n""",
            (today.strftime("%Y-%m"),),
        )
    for table in ("accounts", "transactions", "transfers", "budgets", "transaction_audit"):
        database.conn.execute("ANALYZE " + table)


def main():
    url = validate_database_url(os.environ["BENCH_ISOLATED_URL"], isolated=True)
    password = os.environ["BENCH_PASSWORD"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        os.environ.update(
            {
                "DATABASE_URL": url,
                "BASE_CURRENCY": "USD",
                "BUSINESS_TIMEZONE": "Europe/Belgrade",
                "ENVIRONMENT": "development",
                "OWNER_USERNAME": "owner",
                "OWNER_PASSWORD_HASH": PasswordHasher().hash(password),
                "CORS_ORIGINS": origin,
                "ALLOWED_HOSTS": "127.0.0.1,localhost",
                "TRUSTED_PROXY_IPS": "",
                "DATABASE_POOL_SIZE": "5",
                "DATABASE_POOL_TIMEOUT": "2",
                "DATABASE_POOL_MAX_WAITING": "20",
                "SESSION_SECONDS": "28800",
                "SESSION_IDLE_SECONDS": "1800",
            }
        )
        from backend.app.domain import business_date
        from backend.app.postgres_database import PostgresDatabase

        database = PostgresDatabase(url)
        try:
            seed(database, int(os.environ["BENCH_ROWS"]), business_date.today())
        finally:
            database.close()
        print("BENCH_URL=" + origin, flush=True)
        from backend.app.main import app

        @app.get("/api/benchmark/pool")
        def pool_stats():
            return app.state.database.pool.get_stats()

        uvicorn.Server(
            uvicorn.Config(
                "backend.app.main:app",
                host="127.0.0.1",
                reload=False,
                workers=1,
                access_log=False,
                proxy_headers=False,
                log_level="warning",
            )
        ).run(sockets=[listener])


if __name__ == "__main__":
    main()
