from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Money:
    cents: int
    currency: str = "USD"

    def __post_init__(self):
        normalized = self.currency.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Currency must be a three-letter ISO code")
        object.__setattr__(self, "currency", normalized)

    @classmethod
    def from_amount(cls, amount, currency: str = "USD") -> "Money":
        decimal_amount = Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP)
        return cls(int(decimal_amount * 100), currency)

    @property
    def amount(self) -> Decimal:
        return (Decimal(self.cents) / 100).quantize(CENT)

    def as_float(self) -> float:
        return float(self.amount)

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def _require_same_currency(self, other: "Money"):
        if self.currency != other.currency:
            raise ValueError("Cannot combine money in different currencies")
