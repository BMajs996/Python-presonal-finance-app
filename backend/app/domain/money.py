from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from decimal import InvalidOperation as DecimalError

from .errors import InvalidOperation

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1000000000.00")
MAX_AMOUNT_CENTS = 100_000_000_000
MAX_STATEMENT_BALANCE = Decimal("90000000000000.00")


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
    def from_amount(cls, amount, currency: str = "USD", *, maximum: Decimal = MAX_AMOUNT) -> "Money":
        try:
            decimal_amount = Decimal(str(amount))
            if not decimal_amount.is_finite() or abs(decimal_amount) > maximum:
                raise InvalidOperation("Amount exceeds the supported monetary range")
            decimal_amount = decimal_amount.quantize(CENT, rounding=ROUND_HALF_UP)
        except DecimalError as exc:
            raise InvalidOperation("Invalid monetary amount") from exc
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
