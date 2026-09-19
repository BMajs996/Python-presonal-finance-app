from fastapi import APIRouter, Depends, Query

from ..schemas import MonthlyReportResponse
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/reports", tags=["reports"], responses=ERROR_RESPONSES)


@router.get("/monthly", response_model=MonthlyReportResponse)
def monthly_report(
    months: int = Query(default=12, ge=1, le=60),
    service: FinanceService = Depends(get_finance_service),
):
    return service.monthly_report(months)
