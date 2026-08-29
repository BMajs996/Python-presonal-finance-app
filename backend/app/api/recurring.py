from fastapi import APIRouter, Depends, HTTPException, status

from ..schemas import RecurringCreate, RecurringUpdate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.get("")
def recurring(service: FinanceService = Depends(get_finance_service)):
    return service.recurring()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_recurring(payload: RecurringCreate, service: FinanceService = Depends(get_finance_service)):
    try:
        return service.create_recurring(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{recurring_id}")
def update_recurring(
    recurring_id: int,
    payload: RecurringUpdate,
    service: FinanceService = Depends(get_finance_service),
):
    try:
        updated = service.update_recurring(recurring_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")
    return updated


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(recurring_id: int, service: FinanceService = Depends(get_finance_service)):
    service.delete_recurring(recurring_id)
