from datetime import UTC, datetime

from ..domain.money import Money
from .base_repository import BaseRepository


class TransferRepository(BaseRepository):
    def list(self, limit: int = 100, offset: int = 0):
        rows = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name,
                   f.currency AS currency, to_a.currency AS to_currency
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            ORDER BY t.date DESC, t.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [self._serialize(row) for row in rows]

    def get(self, transfer_id: int):
        row = self.conn.execute(
            """
            SELECT t.*, f.name AS from_account_name, to_a.name AS to_account_name,
                   f.currency AS currency, to_a.currency AS to_currency
            FROM transfers t
            JOIN accounts f ON f.id=t.from_account_id
            JOIN accounts to_a ON to_a.id=t.to_account_id
            WHERE t.id=?
            """,
            (transfer_id,),
        ).fetchone()
        return self._serialize(row) if row else None

    def add(self, payload):
        if payload.from_account_id == payload.to_account_id:
            raise ValueError("Transfer accounts must be different")
        self.resolve_account_id(payload.from_account_id)
        self.resolve_account_id(payload.to_account_id)
        from_currency = self.account_currency(payload.from_account_id)
        to_currency = self.account_currency(payload.to_account_id)
        if from_currency != to_currency:
            raise ValueError("Transfers between different currencies require an exchange rate")
        amount = Money.from_amount(payload.amount, from_currency)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO transfers(
                    date, from_account_id, to_account_id, amount, amount_cents,
                    description, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.from_account_id,
                    payload.to_account_id,
                    amount.as_float(),
                    amount.cents,
                    payload.description.strip(),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.get(cursor.lastrowid)

    def delete(self, transfer_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM transfers WHERE id=?", (transfer_id,))

    @staticmethod
    def _serialize(row):
        if row["currency"] != row["to_currency"]:
            raise ValueError("Stored transfer has mismatched account currencies")
        amount = Money(row["amount_cents"], row["currency"])
        return {
            "id": row["id"],
            "date": row["date"],
            "from_account_id": row["from_account_id"],
            "to_account_id": row["to_account_id"],
            "amount": amount.as_float(),
            "currency": amount.currency,
            "description": row["description"],
            "from_account_name": row["from_account_name"],
            "to_account_name": row["to_account_name"],
            "created_at": row["created_at"],
        }
