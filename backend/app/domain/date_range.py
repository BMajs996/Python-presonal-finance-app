from dataclasses import dataclass
from datetime import date, timedelta

from .errors import InvalidOperation


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date | None = None
    end: date | None = None

    def __post_init__(self):
        if self.start and self.end and self.start > self.end:
            raise InvalidOperation("Start date cannot be after end date")

    @classmethod
    def trailing(cls, days: int, *, end: date | None = None) -> "DateRange":
        if days < 1:
            raise InvalidOperation("Period must contain at least one day")
        end = end or date.today()
        try:
            start = end - timedelta(days=days - 1)
        except OverflowError as exc:
            raise InvalidOperation("Period exceeds the supported date range") from exc
        return cls(start=start, end=end)

    @property
    def days(self) -> int:
        if self.start is None or self.end is None:
            raise InvalidOperation("Period requires both start and end dates")
        return (self.end - self.start).days + 1

    @property
    def start_iso(self) -> str:
        return self.start.isoformat() if self.start else ""

    @property
    def end_iso(self) -> str:
        return self.end.isoformat() if self.end else ""
