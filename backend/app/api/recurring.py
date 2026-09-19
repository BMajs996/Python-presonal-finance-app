from fastapi import APIRouter, Depends, status

from ..domain.errors import NotFound
from ..schemas import RecurringCreate, RecurringResponse, RecurringUpdate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/recurring", tags=["recurring"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[RecurringResponse])
def recurring(service: FinanceService = Depends(get_finance_service)):
    return service.recurring()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RecurringResponse)
def create_recurring(payload: RecurringCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_recurring(payload)


@router.put("/{recurring_id}", response_model=RecurringResponse)
def update_recurring(
    recurring_id: int,
    payload: RecurringUpdate,
    service: FinanceService = Depends(get_finance_service),
):
    updated = service.update_recurring(recurring_id, payload)
    if not updated:
        raise NotFound("Recurring transaction not found")
    return updated


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring(recurring_id: int, service: FinanceService = Depends(get_finance_service)):
    service.delete_recurring(recurring_id)
