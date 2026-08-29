from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TransactionType = Literal["income", "expense"]
Frequency = Literal["daily", "weekly", "monthly", "yearly"]
AccountType = Literal["checking", "savings", "cash", "credit_card", "investment", "other"]


class TransactionCreate(BaseModel):
    date: date
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, decimal_places=2)
    description: str = Field(default="", max_length=500)
    account_id: int | None = Field(default=None, gt=0)

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
    amount: Decimal = Field(gt=0, decimal_places=2)
    description: str = Field(default="", max_length=500)
    frequency: Frequency
    start_date: date
    account_id: int | None = Field(default=None, gt=0)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Category is required")
        return value


class RecurringUpdate(BaseModel):
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, decimal_places=2)
    description: str = Field(default="", max_length=500)
    frequency: Frequency
    next_date: date
    account_id: int | None = Field(default=None, gt=0)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Category is required")
        return value


class BudgetCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    monthly_limit: Decimal = Field(gt=0, decimal_places=2)


class BudgetUpdate(BudgetCreate):
    pass


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AccountType = "checking"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    opening_balance: Decimal = Field(default=Decimal("0"), decimal_places=2)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Account name is required")
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def clean_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        return value


class TransferCreate(BaseModel):
    date: date
    from_account_id: int = Field(gt=0)
    to_account_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, decimal_places=2)
    description: str = Field(default="", max_length=500)


class TransactionResponse(BaseModel):
    id: int
    date: str
    type: str
    category: str
    amount: float
    currency: str
    description: str
    account_id: int | None = None
    account_name: str | None = None


class AccountResponse(BaseModel):
    id: int
    name: str
    type: str
    currency: str
    opening_balance: float
    active: int
    created_at: str
    balance: float
    transaction_count: int


class TransferResponse(BaseModel):
    id: int
    date: str
    from_account_id: int
    to_account_id: int
    amount: float
    currency: str
    description: str
    from_account_name: str
    to_account_name: str
    created_at: str


class BudgetResponse(BaseModel):
    id: int
    category: str
    monthly_limit: float
    currency: str
    month_year: str
    spent: float
    percentage: float


class DashboardResponse(BaseModel):
    currency: str
    period: dict
    balance: float
    income: float
    expenses: float
    net: float
    savings_rate: float
    comparison: dict
    expense_categories: list[dict]
    balance_history: list[dict]
    recent_transactions: list[dict]
    budgets: list[dict]
    accounts: list[dict]
