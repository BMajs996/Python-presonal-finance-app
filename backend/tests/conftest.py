import sys
from pathlib import Path

import pytest

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
