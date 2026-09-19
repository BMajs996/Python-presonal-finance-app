import sqlite3

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
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise Conflict("A budget for this category already exists") from exc
            raise

    def delete(self, budget_id: int):
        return self.repository.delete(budget_id)
