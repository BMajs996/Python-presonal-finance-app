from ..database_errors import INTEGRITY_ERRORS, is_unique_violation
from ..domain.errors import Conflict


class BudgetService:
    def __init__(self, repository):
        self.repository = repository

    def list(self):
        return self.repository.usage()

    def create(self, payload):
        return self.repository.add(payload)

    def update(self, budget_id: int, payload):
        try:
            return self.repository.update(budget_id, payload)
        except INTEGRITY_ERRORS as exc:
            if is_unique_violation(exc):
                raise Conflict("A budget for this category already exists") from exc
            raise

    def delete(self, budget_id: int):
        return self.repository.delete(budget_id)
