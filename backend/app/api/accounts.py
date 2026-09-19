from fastapi import APIRouter, Depends, status

from ..domain.errors import NotFound
from ..schemas import AccountCreate, AccountResponse
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/accounts", tags=["accounts"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[AccountResponse])
def accounts(service: FinanceService = Depends(get_finance_service)):
    return service.accounts()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AccountResponse)
def create_account(payload: AccountCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_account(payload)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_account(account_id: int, service: FinanceService = Depends(get_finance_service)):
    if not service.get_account(account_id):
        raise NotFound("Account not found")
    service.deactivate_account(account_id)
