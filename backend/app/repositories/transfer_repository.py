from datetime import UTC, datetime

from .base_repository import BaseRepository


class TransferRepository(BaseRepository):
    def list(self, limit: int = 100, offset: int = 0):
        rows = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            ORDER BY t.date DESC, t.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def get(self, transfer_id: int):
        row = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            WHERE t.id=?
            """,
            (transfer_id,),
        ).fetchone()
        return dict(row) if row else None

    def add(self, payload):
        if payload.from_account_id == payload.to_account_id:
            raise ValueError("Transfer accounts must be different")
        self.resolve_account_id(payload.from_account_id)
        self.resolve_account_id(payload.to_account_id)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO transfers(date, from_account_id, to_account_id, amount, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.from_account_id,
                    payload.to_account_id,
                    payload.amount,
                    payload.description.strip(),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.get(cursor.lastrowid)

    def delete(self, transfer_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM transfers WHERE id=?", (transfer_id,))
