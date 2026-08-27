from dataclasses import dataclass

from .money import Money


@dataclass(frozen=True, slots=True)
class Account:
    id: int
    name: str
    type: str
    currency: str
    opening_balance: Money
    balance: Money
    active: bool
    created_at: str
    transaction_count: int

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("Account name is required")
        if self.currency != self.opening_balance.currency or self.currency != self.balance.currency:
            raise ValueError("Account balances must use the account currency")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "currency": self.currency,
            "opening_balance": self.opening_balance.as_float(),
            "balance": self.balance.as_float(),
            "active": int(self.active),
            "created_at": self.created_at,
            "transaction_count": self.transaction_count,
        }
