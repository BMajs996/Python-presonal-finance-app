from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .domain.category import clean_category
from .domain.money import MAX_AMOUNT
from .money_schemas import CentsMoneyResponse, MoneyContract

TransactionType = Literal["income", "expense"]
Frequency = Literal["daily", "weekly", "monthly", "yearly"]
AccountType = Literal["checking", "savings", "cash", "credit_card", "investment", "other"]


class TransactionCreate(BaseModel):
    date: date
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)
    description: str = Field(default="", max_length=500)
    account_id: int | None = Field(default=None, gt=0)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        return clean_category(value)


class TransactionUpdate(TransactionCreate):
    pass


class RecurringCreate(BaseModel):
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)
    description: str = Field(default="", max_length=500)
    frequency: Frequency
    start_date: date = Field(ge=date(1900, 1, 1), le=date(9998, 12, 31))
    account_id: int | None = Field(default=None, gt=0)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        return clean_category(value)


class RecurringUpdate(BaseModel):
    type: TransactionType
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)
    description: str = Field(default="", max_length=500)
    frequency: Frequency
    next_date: date = Field(ge=date(1900, 1, 1), le=date(9998, 12, 31))
    account_id: int | None = Field(default=None, gt=0)

    @field_validator("category")
    @classmethod
    def clean_category(cls, value: str) -> str:
        return clean_category(value)


class BudgetCreate(BaseModel):
    _clean_category = field_validator("category")(clean_category)

    category: str = Field(min_length=1, max_length=100)
    monthly_limit: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)


class BudgetUpdate(BudgetCreate):
    pass


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AccountType = "checking"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=-MAX_AMOUNT, le=MAX_AMOUNT, decimal_places=2)

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
    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, decimal_places=2)
    description: str = Field(default="", max_length=500)


class TransactionResponse(BaseModel):
    money: MoneyContract
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
    money: MoneyContract
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
    money: MoneyContract
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
    money: MoneyContract
    id: int
    category: str
    monthly_limit: float
    currency: str
    month_year: str
    spent: float
    percentage: float


class TransactionPage(BaseModel):
    items: list[TransactionResponse]
    total: int


class RecurringResponse(BaseModel):
    money: MoneyContract
    id: int
    type: str
    category: str
    amount: float
    description: str | None
    frequency: str
    next_date: str
    active: int
    account_id: int | None
    account_name: str | None
    currency: str


class PeriodResponse(BaseModel):
    days: int
    start: str
    end: str


class ComparisonResponse(BaseModel):
    income: float | None
    expenses: float | None
    net: float | None


class CategoryTotal(BaseModel):
    money: MoneyContract
    category: str
    total: float


class BalancePoint(BaseModel):
    money: MoneyContract
    date: str
    balance: float


class ReportSummary(BaseModel):
    money: MoneyContract
    income: float
    expenses: float
    net: float
    savings_rate: float


class MonthlyPoint(ReportSummary):
    month: str
    balance: float


class CategoryTrend(BaseModel):
    money: MoneyContract
    category: str
    totals: list[float]


class MonthlyReportResponse(BaseModel):
    currency: str
    months: list[MonthlyPoint]
    top_categories: list[CategoryTotal]
    category_trends: list[CategoryTrend]
    summary: ReportSummary


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok"]


class DashboardResponse(BaseModel):
    money: MoneyContract
    currency: str
    period: PeriodResponse
    balance: float
    income: float
    expenses: float
    net: float
    savings_rate: float
    comparison: ComparisonResponse
    expense_categories: list[CategoryTotal]
    balance_history: list[BalancePoint]
    recent_transactions: list[TransactionResponse]
    budgets: list[BudgetResponse]
    accounts: list[AccountResponse]


class DeletedTransactionResponse(TransactionResponse):
    deleted_at: str


class DeletedTransactionPage(BaseModel):
    items: list[DeletedTransactionResponse]
    total: int


class TransactionSnapshot(CentsMoneyResponse):
    id: int
    date: str
    type: str
    category: str
    amount_cents: int
    description: str | None
    account_id: int | None
    account_name: str | None
    currency: str | None
    deleted_at: str | None


class TransactionAuditResponse(BaseModel):
    id: int
    transaction_id: int
    action: Literal["created", "updated", "deleted", "restored"]
    occurred_at: str
    actor: str
    before_state: TransactionSnapshot | None
    after_state: TransactionSnapshot


class TransactionAuditPage(BaseModel):
    items: list[TransactionAuditResponse]
    total: int


class CsvRows(BaseModel):
    rows: list[TransactionCreate] = Field(min_length=1, max_length=1000)


class CsvImport(CsvRows):
    batch_id: UUID


class CsvPreviewRow(BaseModel):
    status: Literal["valid", "invalid", "duplicate"]
    error: str


class CsvPreview(BaseModel):
    rows: list[CsvPreviewRow]


class CsvResult(BaseModel):
    imported: int
    duplicates: int


class LedgerPolicy(BaseModel):
    business_timezone: str
    business_date: date
    model: Literal["posted-only"]
