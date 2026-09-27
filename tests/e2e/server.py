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
        from argon2 import PasswordHasher

        os.environ["OWNER_PASSWORD_HASH"] = PasswordHasher().hash("synthetic-owner-password")
        os.environ["OWNER_USERNAME"] = "owner"
        os.environ["ENVIRONMENT"] = "development"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            os.environ["CORS_ORIGINS"] = f"http://127.0.0.1:{listener.getsockname()[1]}"
            print(f"E2E_URL=http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
            server = uvicorn.Server(uvicorn.Config("backend.app.main:app", log_level="warning"))
            server.run(sockets=[listener])
