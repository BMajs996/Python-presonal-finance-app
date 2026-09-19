from fastapi import APIRouter, Depends, status

from ..domain.errors import NotFound
from ..schemas import BudgetCreate, BudgetResponse, BudgetUpdate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/budgets", tags=["budgets"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[BudgetResponse])
def budgets(service: FinanceService = Depends(get_finance_service)):
    return service.budgets()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=BudgetResponse)
def create_budget(payload: BudgetCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_budget(payload)


@router.put("/{budget_id}", response_model=BudgetResponse)
def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    service: FinanceService = Depends(get_finance_service),
):
    updated = service.update_budget(budget_id, payload)
    if not updated:
        raise NotFound("Budget not found")
    return updated


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: int, service: FinanceService = Depends(get_finance_service)):
    service.delete_budget(budget_id)
