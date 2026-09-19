import sqlite3

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
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise Conflict("An account with this name already exists") from exc
            raise

    def deactivate(self, account_id: int):
        return self.repository.deactivate(account_id)
