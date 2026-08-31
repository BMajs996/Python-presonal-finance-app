from collections.abc import Iterator

from fastapi import Request

from ..database import FinanceDatabase
from ..repositories.finance_repository import FinanceRepository
from ..services.finance_service import FinanceService


def get_finance_service(request: Request) -> Iterator[FinanceService]:
    database: FinanceDatabase = request.app.state.database
    with database.connection() as connection:
        repository = FinanceRepository(
            database,
            database.base_currency,
            connection=connection,
        )
        yield FinanceService(repository)
