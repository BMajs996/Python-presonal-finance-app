"""Business date shared by posted-ledger validation and queries."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date

from .errors import InvalidOperation

_current: ContextVar[date | None] = ContextVar("business_date", default=None)


def today() -> date:
    return _current.get() or date.today()


@contextmanager
def snapshot():
    token = _current.set(today())
    try:
        yield
    finally:
        _current.reset(token)


def require_posted(value: date) -> None:
    if value > today():
        raise InvalidOperation("Future-dated entries are not allowed; use a recurring schedule instead")
