from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..schemas import TransactionCreate, TransactionUpdate
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("")
def list_transactions(
    service: FinanceService = Depends(get_finance_service),
    search: str = "",
    category: str = "",
    type_: str = Query(default="", alias="type"),
    account_id: int | None = Query(default=None, gt=0),
    date_start: date | None = None,
    date_end: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        rows, total = service.list_transactions(
            search=search,
            category=category,
            type_=type_,
            account_id=account_id,
            date_start=date_start,
            date_end=date_end,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": rows, "total": total}


@router.post("", status_code=201)
def create_transaction(payload: TransactionCreate, service: FinanceService = Depends(get_finance_service)):
    try:
        return service.create_transaction(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{transaction_id}")
def update_transaction(
    transaction_id: int, payload: TransactionUpdate, service: FinanceService = Depends(get_finance_service)
):
    if not service.get_transaction(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        return service.update_transaction(transaction_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, service: FinanceService = Depends(get_finance_service)):
    if not service.get_transaction(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    service.delete_transaction(transaction_id)
