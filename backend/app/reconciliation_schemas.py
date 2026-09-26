from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class StatementCreate(BaseModel):
    account_id: int = Field(gt=0)
    closing_date: date
    closing_balance: Decimal = Field(decimal_places=2, ge=-90000000000000, le=90000000000000)


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


class StatementDetail(StatementSummary):
    account_name: str
    currency: str
    cleared_balance_cents: int
    difference_cents: int
    entries: list[StatementEntry]
