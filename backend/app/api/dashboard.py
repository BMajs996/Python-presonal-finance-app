from fastapi import APIRouter, Depends, Query

from ..core.config import settings
from ..domain import business_date
from ..schemas import DashboardResponse, LedgerPolicy
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api", tags=["dashboard"], responses=ERROR_RESPONSES)


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    days: int = Query(default=30, ge=1, le=3650), service: FinanceService = Depends(get_finance_service)
):
    return service.dashboard(days)


@router.get("/categories", response_model=list[str])
def categories(service: FinanceService = Depends(get_finance_service)):
    return service.categories()


@router.get("/ledger-policy", response_model=LedgerPolicy)
def ledger_policy():
    return {
        "business_date": business_date.today(),
        "business_timezone": settings.business_timezone,
        "model": "posted-only",
    }
