import sqlite3


class BaseRepository:
    def __init__(self, connection: sqlite3.Connection, base_currency: str = "USD"):
        self.conn = connection
        self.base_currency = base_currency

    def default_account_id(self) -> int:
        row = self.conn.execute("SELECT id FROM accounts WHERE name='Main Account' LIMIT 1").fetchone()
        if not row:
            raise RuntimeError("Main Account is missing")
        return int(row["id"])

    def resolve_account_id(self, account_id: int | None) -> int:
        resolved = self.default_account_id() if account_id is None else account_id
        row = self.conn.execute("SELECT id FROM accounts WHERE id=? AND active=1", (resolved,)).fetchone()
        if not row:
            raise ValueError(f"Account {resolved} does not exist or is inactive")
        return resolved

    def account_currency(self, account_id: int) -> str:
        row = self.conn.execute("SELECT currency FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise ValueError(f"Account {account_id} does not exist")
        return row["currency"]

    @staticmethod
    def inserted_id(cursor: sqlite3.Cursor) -> int:
        if cursor.lastrowid is None:
            raise RuntimeError("Database insert did not return an id")
        return cursor.lastrowid
