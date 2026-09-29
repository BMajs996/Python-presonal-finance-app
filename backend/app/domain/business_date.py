"""Business date shared by posted-ledger validation and queries."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ..core.config import settings
from .errors import InvalidOperation

_current: ContextVar[date | None] = ContextVar("business_date", default=None)


def utc_now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    captured = _current.get()
    if captured is not None:
        return captured
    return _date_at(utc_now())


def _date_at(instant: datetime) -> date:
    if instant.utcoffset() is None:
        raise ValueError("Business clock must return a timezone-aware instant")
    return instant.astimezone(ZoneInfo(settings.business_timezone)).date()


@contextmanager
def snapshot(clock: Callable[[], datetime] | None = None):
    token = _current.set(_date_at(clock()) if clock is not None else today())
    try:
        yield
    finally:
        _current.reset(token)


def require_posted(value: date) -> None:
    if value > today():
        raise InvalidOperation("Future-dated entries are not allowed; use a recurring schedule instead")
