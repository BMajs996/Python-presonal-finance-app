from fastapi import APIRouter, Depends, Query, status

from ..domain.errors import NotFound
from ..schemas import TransferCreate, TransferResponse
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/transfers", tags=["transfers"], responses=ERROR_RESPONSES)


@router.get("", response_model=list[TransferResponse])
def transfers(
    service: FinanceService = Depends(get_finance_service),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return service.transfers(limit=limit, offset=offset)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransferResponse)
def create_transfer(payload: TransferCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_transfer(payload)


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer(transfer_id: int, service: FinanceService = Depends(get_finance_service)):
    if not service.get_transfer(transfer_id):
        raise NotFound("Transfer not found")
    service.delete_transfer(transfer_id)
