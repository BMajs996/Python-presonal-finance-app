from fastapi import APIRouter, Depends, Query

from .dependencies import get_finance_service
from ..services.finance_service import FinanceService

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/monthly")
def monthly_report(
    months: int = Query(default=12, ge=1, le=60),
    service: FinanceService = Depends(get_finance_service),
):
    return service.monthly_report(months)
