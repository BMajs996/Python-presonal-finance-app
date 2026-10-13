from typing import Any

from ..domain.errors import InvalidOperation, NotFound


class BaseRepository:
    def __init__(self, connection: Any, base_currency: str = "USD", *, user_id: int = 1):
        if type(user_id) is not int or user_id <= 0:
            raise ValueError("An explicit valid financial owner is required")
        self.conn = connection
        self.base_currency = base_currency
        self.user_id = user_id

    def default_account_id(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE user_id=? AND name='Main Account' LIMIT 1", (self.user_id,)
        ).fetchone()
        if not row:
            raise RuntimeError("Main Account is missing")
        return int(row["id"])

    def resolve_account_id(self, account_id: int | None) -> int:
        resolved = self.default_account_id() if account_id is None else account_id
        row = self.conn.execute(
            "SELECT id, active FROM accounts WHERE id=? AND user_id=?", (resolved, self.user_id)
        ).fetchone()
        if not row:
            raise NotFound("Account not found")
        if not row["active"]:
            raise InvalidOperation("Account is inactive")
        return resolved

    def account_currency(self, account_id: int) -> str:
        row = self.conn.execute(
            "SELECT currency FROM accounts WHERE id=? AND user_id=?", (account_id, self.user_id)
        ).fetchone()
        if not row:
            raise NotFound("Account not found")
        return row["currency"]

    @staticmethod
    def inserted_id(cursor: Any) -> int:
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Database insert did not return an id")
        return int(row["id"])
