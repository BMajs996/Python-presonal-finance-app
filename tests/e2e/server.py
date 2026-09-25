"""Launch a real API on an ephemeral port with disposable financial data."""

import os
import socket
import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="finance-e2e-") as directory:
        os.environ["DATABASE_PATH"] = str(Path(directory) / "test.db")
        os.environ["BASE_CURRENCY"] = "USD"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            print(f"E2E_URL=http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
            server = uvicorn.Server(uvicorn.Config("backend.app.main:app", log_level="warning"))
            server.run(sockets=[listener])
