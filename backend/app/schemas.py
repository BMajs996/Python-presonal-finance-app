from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TransactionType = Literal["income", "expense"]
Frequency = Literal["daily", "weekly", "monthly", "yearly"]


class TransactionCreate(BaseModel):
    date: date
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)
    description: str = Field(default="", max_length=500)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Category is required")
        return value


class TransactionUpdate(TransactionCreate):
    pass


class RecurringCreate(BaseModel):
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0)
    description: str = Field(default="", max_length=500)
    frequency: Frequency
    start_date: date


class BudgetCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    monthly_limit: float = Field(gt=0)


class TransactionResponse(BaseModel):
    id: int
    date: str
    type: str
    category: str
    amount: float
    description: str


class BudgetResponse(BaseModel):
    id: int
    category: str
    monthly_limit: float
    month_year: str
    spent: float
    percentage: float


class DashboardResponse(BaseModel):
    balance: float
    income: float
    expenses: float
    net: float
    expense_categories: list[dict]
    balance_history: list[dict]
    recent_transactions: list[dict]
    budgets: list[dict]
