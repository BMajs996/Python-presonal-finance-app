from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date | None = None
    end: date | None = None

    def __post_init__(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("Start date cannot be after end date")

    @property
    def start_iso(self) -> str:
        return self.start.isoformat() if self.start else ""

    @property
    def end_iso(self) -> str:
        return self.end.isoformat() if self.end else ""
