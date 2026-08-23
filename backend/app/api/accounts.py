from fastapi import APIRouter, Depends, HTTPException, status

from ..schemas import AccountCreate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
def accounts(service: FinanceService = Depends(get_finance_service)):
    return service.accounts()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, service: FinanceService = Depends(get_finance_service)):
    try:
        return service.create_account(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_account(account_id: int, service: FinanceService = Depends(get_finance_service)):
    if not service.get_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        service.deactivate_account(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
