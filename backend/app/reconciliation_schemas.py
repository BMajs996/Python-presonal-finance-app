from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .domain.money import MAX_STATEMENT_BALANCE


class StatementCreate(BaseModel):
    account_id: int = Field(gt=0)
    closing_date: date
    closing_balance: Decimal = Field(decimal_places=2, ge=-MAX_STATEMENT_BALANCE, le=MAX_STATEMENT_BALANCE)


class ClearedEntry(BaseModel):
    kind: Literal["transaction", "transfer"]
    entry_id: int = Field(gt=0)
    cleared: bool


class StatementSummary(BaseModel):
    id: int
    account_id: int
    closing_date: str
    opening_balance_cents: int
    closing_balance_cents: int
    status: Literal["draft", "completed"]
    created_at: str
    completed_at: str | None


class StatementEntry(BaseModel):
    account_id: int
    entry_id: int
    kind: Literal["transaction", "transfer"]
    date: str
    description: str
    label: str
    amount_cents: int
    cleared: bool


class StatementTotals(StatementSummary):
    account_name: str
    currency: str
    cleared_balance_cents: int
    difference_cents: int
    total_entries: int
    cleared_count: int


class StatementDetail(StatementTotals):
    entries: list[StatementEntry]
    next_cursor: str | None


class EntryCursor(BaseModel):
    date: date
    kind: Literal["transaction", "transfer"]
    entry_id: int = Field(gt=0)
