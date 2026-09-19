class DomainError(ValueError):
    """An expected failure of a financial operation."""


class InvalidOperation(DomainError):
    pass


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass
