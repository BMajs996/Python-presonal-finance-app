import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def db(tmp_path):
    from app.database import FinanceDatabase

    database = FinanceDatabase(tmp_path / "test.db")
    yield database
    database.close()
