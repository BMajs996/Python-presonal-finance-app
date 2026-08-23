from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..schemas import TransferCreate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


@router.get("")
def transfers(
    service: FinanceService = Depends(get_finance_service),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return service.transfers(limit=limit, offset=offset)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_transfer(payload: TransferCreate, service: FinanceService = Depends(get_finance_service)):
    try:
        return service.create_transfer(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer(transfer_id: int, service: FinanceService = Depends(get_finance_service)):
    if not service.get_transfer(transfer_id):
        raise HTTPException(status_code=404, detail="Transfer not found")
    service.delete_transfer(transfer_id)
