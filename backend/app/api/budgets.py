from fastapi import APIRouter, Depends, HTTPException, status

from ..schemas import BudgetCreate, BudgetUpdate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("")
def budgets(service: FinanceService = Depends(get_finance_service)):
    return service.budgets()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_budget(payload: BudgetCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_budget(payload)


@router.put("/{budget_id}")
def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    service: FinanceService = Depends(get_finance_service),
):
    updated = service.update_budget(budget_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Budget not found")
    return updated


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: int, service: FinanceService = Depends(get_finance_service)):
    service.delete_budget(budget_id)
