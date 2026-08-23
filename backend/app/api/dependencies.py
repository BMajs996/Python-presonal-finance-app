from fastapi import Request

from ..services.finance_service import FinanceService


def get_finance_service(request: Request) -> FinanceService:
    return request.app.state.finance_service
