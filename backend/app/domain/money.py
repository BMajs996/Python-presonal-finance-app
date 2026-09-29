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

    def as_decimal_string(self) -> str:
        sign = "-" if self.cents < 0 else ""
        whole, fraction = divmod(abs(self.cents), 100)
        return f"{sign}{whole}.{fraction:02d}"

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def _require_same_currency(self, other: "Money"):
        if self.currency != other.currency:
            raise ValueError("Cannot combine money in different currencies")


def money_contract(currency: str, **values: int | list[int]) -> dict:
    """Versioned exact values derived from cents, never from legacy JSON floats."""
    return {
        "version": "decimal-v1",
        "currency": currency,
        "values": {
            key: (
                [Money(item, currency).as_decimal_string() for item in value]
                if isinstance(value, list)
                else Money(value, currency).as_decimal_string()
            )
            for key, value in values.items()
        },
    }
