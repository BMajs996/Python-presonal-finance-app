from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from ..reconciliation_schemas import (
    ClearedEntry,
    EntryCursor,
    StatementCreate,
    StatementDetail,
    StatementSummary,
    StatementTotals,
)
from ..repositories.reconciliation_repository import ReconciliationRepository
from ..schemas import AccountResponse
from ..services.reconciliation_service import ReconciliationService
from .errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/reconciliations", tags=["reconciliation"], responses=ERROR_RESPONSES)


def get_service(request: Request):
    database = request.app.state.database
    with database.connection() as connection:
        yield ReconciliationService(ReconciliationRepository(connection, database.base_currency))


@router.get("", response_model=list[StatementSummary])
def statements(account_id: int = Query(gt=0), service=Depends(get_service)):
    return service.list(account_id)


@router.post("", status_code=201, response_model=StatementDetail)
def create(payload: StatementCreate, service=Depends(get_service)):
    return service.create(payload)


@router.get("/accounts", response_model=list[AccountResponse])
def accounts(service=Depends(get_service)):
    return service.accounts()


@router.get("/{ident}", response_model=StatementDetail)
def detail(
    ident: int,
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=200),
    service=Depends(get_service),
):
    try:
        after = EntryCursor.model_validate_json(cursor) if cursor else None
    except ValidationError as exc:
        raise HTTPException(422, "Invalid entry cursor") from exc
    return service.detail(ident, limit, after)


@router.put("/{ident}/entries", response_model=StatementTotals)
def clear(ident: int, payload: ClearedEntry, service=Depends(get_service)):
    return service.clear(ident, payload)


@router.post("/{ident}/complete", response_model=StatementDetail)
def complete(ident: int, service=Depends(get_service)):
    return service.complete(ident)


@router.delete("/{ident}", status_code=204)
def cancel(ident: int, service=Depends(get_service)):
    service.cancel(ident)
