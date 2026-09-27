from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from ..domain.errors import NotFound
from ..repositories.transaction_repository import TransactionRepository
from ..schemas import (
    CsvImport,
    CsvPreview,
    CsvResult,
    CsvRows,
    DeletedTransactionPage,
    TransactionAuditPage,
    TransactionCreate,
    TransactionPage,
    TransactionResponse,
    TransactionUpdate,
)
from ..services.csv_import_service import CsvImportService
from ..services.finance_service import FinanceService
from .dependencies import get_finance_service
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/transactions", tags=["transactions"], responses=ERROR_RESPONSES)


@router.get("", response_model=TransactionPage)
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
    return {"items": rows, "total": total}


@router.get("/deleted", response_model=DeletedTransactionPage)
def deleted_transactions(
    service: FinanceService = Depends(get_finance_service),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows, total = service.list_transactions(deleted=True, limit=limit, offset=offset)
    return {"items": rows, "total": total}


@router.post("/{transaction_id}/restore", response_model=TransactionResponse)
def restore_transaction(transaction_id: int, service: FinanceService = Depends(get_finance_service)):
    return service.restore_transaction(transaction_id)


@router.get("/{transaction_id}/history", response_model=TransactionAuditPage)
def transaction_history(
    transaction_id: int,
    service: FinanceService = Depends(get_finance_service),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return service.transaction_history(transaction_id, limit, offset)


@router.post("", status_code=201, response_model=TransactionResponse)
def create_transaction(payload: TransactionCreate, service: FinanceService = Depends(get_finance_service)):
    return service.create_transaction(payload)


@router.put("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: int, payload: TransactionUpdate, service: FinanceService = Depends(get_finance_service)
):
    updated = service.update_transaction(transaction_id, payload)
    if updated is None:
        raise NotFound("Transaction not found")
    return updated


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, service: FinanceService = Depends(get_finance_service)):
    if not service.delete_transaction(transaction_id):
        raise NotFound("Transaction not found")


def get_csv_service(request: Request):
    database = request.app.state.database
    with database.connection() as connection:
        yield CsvImportService(TransactionRepository(connection, database.base_currency))


@router.post("/import/preview", response_model=CsvPreview)
def preview_csv(payload: CsvRows, service=Depends(get_csv_service)):
    return service.preview(payload.rows)


@router.post("/import", response_model=CsvResult)
def import_csv(payload: CsvImport, service=Depends(get_csv_service)):
    return service.commit(payload)
