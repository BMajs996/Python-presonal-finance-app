from dataclasses import dataclass
from datetime import date

from .money import Money


@dataclass(frozen=True, slots=True)
class Transaction:
    id: int
    date: date
    type: str
    category: str
    amount: Money
    description: str
    account_id: int
    account_name: str

    def __post_init__(self):
        if self.type not in {"income", "expense"}:
            raise ValueError("Transaction type must be income or expense")
        if not self.category.strip():
            raise ValueError("Transaction category is required")
        if self.amount.cents <= 0:
            raise ValueError("Transaction amount must be positive")

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "type": self.type,
            "category": self.category,
            "amount": self.amount.as_float(),
            "currency": self.amount.currency,
            "description": self.description,
            "account_id": self.account_id,
            "account_name": self.account_name,
        }
