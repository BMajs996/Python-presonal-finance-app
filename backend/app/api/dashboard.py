from fastapi import APIRouter, Depends, Query

from .dependencies import get_finance_service
from ..services.finance_service import FinanceService

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(days: int = Query(default=30, ge=1, le=3650), service: FinanceService = Depends(get_finance_service)):
    return service.dashboard(days)


@router.get("/categories")
def categories(service: FinanceService = Depends(get_finance_service)):
    return service.categories()
