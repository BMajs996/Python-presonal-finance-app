import sqlite3


class BaseRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    def default_account_id(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE name='Main Account' LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("Main Account is missing")
        return int(row["id"])

    def resolve_account_id(self, account_id: int | None) -> int:
        resolved = self.default_account_id() if account_id is None else account_id
        row = self.conn.execute(
            "SELECT id FROM accounts WHERE id=? AND active=1", (resolved,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account {resolved} does not exist or is inactive")
        return resolved
