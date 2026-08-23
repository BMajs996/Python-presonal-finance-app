from fastapi import APIRouter, Depends, status

from .dependencies import get_finance_service
from ..schemas import BudgetCreate
from ..services.finance_service import FinanceService

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("")
def budgets(service: FinanceService = Depends(get_finance_service)):
    return service.budgets()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_budget(payload: BudgetCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_budget(payload)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(budget_id: int, service: FinanceService = Depends(get_finance_service)):
    service.delete_budget(budget_id)
