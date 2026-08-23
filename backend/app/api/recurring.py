from fastapi import APIRouter, Depends, status

from .dependencies import get_finance_service
from ..schemas import RecurringCreate
from ..services.finance_service import FinanceService

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.get("")
def recurring(service: FinanceService = Depends(get_finance_service)):
    return service.recurring()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_recurring(payload: RecurringCreate, service: FinanceService = Depends(get_finance_service)):
    try:
        return service.create_recurring(payload)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(recurring_id: int, service: FinanceService = Depends(get_finance_service)):
    service.delete_recurring(recurring_id)
