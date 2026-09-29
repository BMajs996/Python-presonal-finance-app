"""Launch a real API on an ephemeral port with disposable financial data."""

import os
import socket
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
    with ExitStack() as stack:
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="finance-e2e-"))
        os.environ["DATABASE_URL"] = ""
        if url := os.environ.get("E2E_DATABASE_URL"):
            from backend.tests.postgres_helpers import temporary_schema

            os.environ["DATABASE_URL"] = stack.enter_context(temporary_schema(url))
        os.environ["DATABASE_PATH"] = str(Path(directory) / "test.db")
        os.environ["BASE_CURRENCY"] = "USD"
        os.environ["BUSINESS_TIMEZONE"] = "Europe/Belgrade"
        from argon2 import PasswordHasher

        os.environ["OWNER_PASSWORD_HASH"] = PasswordHasher().hash("synthetic-owner-password")
        os.environ["OWNER_USERNAME"] = "owner"
        os.environ["ENVIRONMENT"] = "development"
        if os.environ.get("E2E_LEDGER_SCENARIO") == "1":
            from datetime import UTC, date, datetime, timedelta

            from backend.app.core.config import settings
            from backend.app.database_factory import open_database
            from backend.app.domain import business_date
            from backend.app.main import app
            from backend.app.repositories.account_repository import AccountRepository
            from backend.app.repositories.budget_repository import BudgetRepository
            from backend.app.repositories.transaction_repository import TransactionRepository
            from backend.app.repositories.transfer_repository import TransferRepository
            from backend.app.schemas import AccountCreate, BudgetCreate, TransactionCreate, TransferCreate

            current_instant = [datetime(2026, 9, 10, 21, 59, 59, tzinfo=UTC)]

            business_date.utc_now = lambda: current_instant[0]
            database = open_database(settings)
            try:
                with database.connection() as conn:
                    accounts = AccountRepository(conn)
                    first = accounts.default_account_id()
                    second = accounts.add(AccountCreate(name="Savings"))["id"]
                    for kind, amount, description in [
                        ("income", "100", "Future income"),
                        ("expense", "20", "Future expense"),
                    ]:
                        TransactionRepository(conn).add(
                            TransactionCreate(
                                date=date(2026, 9, 11),
                                type=kind,
                                category="Food",
                                amount=amount,
                                description=description,
                                account_id=first,
                            )
                        )
                    TransferRepository(conn).add(
                        TransferCreate(
                            date=date(2026, 9, 11),
                            from_account_id=first,
                            to_account_id=second,
                            amount="30",
                            description="Future transfer",
                        )
                    )
                    BudgetRepository(conn).add(BudgetCreate(category="Food", monthly_limit="100"))
            finally:
                database.close()

            # These routes and clock exist only in this disposable test server, never the production app.
            @app.post("/api/e2e/advance-business-day")
            def advance_business_day():
                current_instant[0] += timedelta(days=1)
                return {"advanced": True}

            @app.post("/api/e2e/cross-midnight")
            def cross_midnight():
                current_instant[0] += timedelta(seconds=1)
                return {"advanced": True}

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            os.environ["CORS_ORIGINS"] = f"http://127.0.0.1:{listener.getsockname()[1]}"
            if os.environ.get("E2E_LEDGER_SCENARIO") == "1":
                settings.cors_origins = os.environ["CORS_ORIGINS"]
            print(f"E2E_URL=http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
            server = uvicorn.Server(uvicorn.Config("backend.app.main:app", log_level="warning"))
            server.run(sockets=[listener])
