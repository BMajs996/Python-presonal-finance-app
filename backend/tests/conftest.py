import sys
from pathlib import Path

import pytest
from argon2 import PasswordHasher

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def db(tmp_path):
    from app.database import FinanceDatabase
    from app.repositories.finance_repository import FinanceRepository

    database = FinanceDatabase(tmp_path / "test.db")
    repository = FinanceRepository(database)
    yield repository
    repository.close()


@pytest.fixture
def finance_service(db):
    from app.services.finance_service import FinanceService

    return FinanceService(db)


@pytest.fixture(autouse=True)
def isolate_database_url(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "database_url", None)


@pytest.fixture(autouse=True)
def owner_settings(monkeypatch):
    from app.core.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "owner_username", "owner")
    monkeypatch.setattr(settings, "owner_password_hash", SecretStr(TEST_OWNER_HASH))
    monkeypatch.setattr(settings, "cors_origins", "http://testserver")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "allowed_hosts", "testserver,localhost,127.0.0.1")


TEST_PASSWORD = "synthetic-owner-password"
TEST_OWNER_HASH = PasswordHasher().hash(TEST_PASSWORD)


def login_client(client):
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]})
