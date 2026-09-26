from ..database_errors import INTEGRITY_ERRORS, is_unique_violation
from ..domain.errors import Conflict


class AccountService:
    def __init__(self, repository):
        self.repository = repository

    def list(self):
        return self.repository.list()

    def get(self, account_id: int):
        return self.repository.get(account_id)

    def create(self, payload):
        try:
            return self.repository.add(payload)
        except INTEGRITY_ERRORS as exc:
            if is_unique_violation(exc):
                raise Conflict("An account with this name already exists") from exc
            raise

    def deactivate(self, account_id: int):
        return self.repository.deactivate(account_id)
