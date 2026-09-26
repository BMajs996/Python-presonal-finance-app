import json
from datetime import UTC, date, datetime

from ..domain.errors import NotFound
from ..domain.money import Money
from ..domain.transaction import Transaction
from .base_repository import BaseRepository


class TransactionRepository(BaseRepository):
    def list(
        self,
        search: str = "",
        category: str = "",
        type_: str = "",
        account_id: int | None = None,
        date_start: str = "",
        date_end: str = "",
        limit: int = 100,
        offset: int = 0,
        deleted: bool = False,
    ):
        query = """
            SELECT t.*, a.name AS account_name, a.currency AS account_currency
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            WHERE (t.deleted_at IS NOT NULL) = ?
        """
        params: list[str | int] = [int(deleted)]
        if search:
            query += " AND (t.description LIKE ? OR t.category LIKE ? OR a.name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if category:
            query += " AND t.category=?"
            params.append(category)
        if type_:
            query += " AND t.type=?"
            params.append(type_)
        if account_id is not None:
            query += " AND t.account_id=?"
            params.append(account_id)
        if date_start:
            query += " AND t.date>=?"
            params.append(date_start)
        if date_end:
            query += " AND t.date<=?"
            params.append(date_end)

        # Query fragments are fixed above and all request values remain bound parameters.
        count_sql = f"SELECT COUNT(*) FROM ({query})"
        total = self.conn.execute(count_sql, params).fetchone()[0]
        query += " ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?"
        rows = self.conn.execute(query, [*params, limit, offset]).fetchall()
        items = [self._to_domain(row).to_dict() for row in rows]
        if deleted:
            for item, row in zip(items, rows, strict=True):
                item["deleted_at"] = row["deleted_at"]
        return items, total

    def get(self, transaction_id: int, include_deleted: bool = False):
        row = self.conn.execute(
            """
            SELECT t.*, a.name AS account_name, a.currency AS account_currency
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            WHERE t.id=? AND (? OR t.deleted_at IS NULL)
            """,
            (transaction_id, include_deleted),
        ).fetchone()
        return self._to_domain(row).to_dict() if row else None

    def add(self, payload):
        account_id = self.resolve_account_id(payload.account_id)
        amount = Money.from_amount(payload.amount, self.account_currency(account_id))
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO transactions(
                    date, type, category, amount, amount_cents, description, account_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    amount.as_float(),
                    amount.cents,
                    payload.description.strip(),
                    account_id,
                ),
            )
        return self.get(self.inserted_id(cursor))

    def update(self, transaction_id: int, payload):
        existing = self.get(transaction_id)
        if not existing:
            return None
        account_id = (
            self.resolve_account_id(payload.account_id)
            if payload.account_id is not None
            else existing["account_id"]
        )
        amount = Money.from_amount(payload.amount, self.account_currency(account_id))
        with self.conn:
            self.conn.execute(
                """
                UPDATE transactions
                SET date=?, type=?, category=?, amount=?, amount_cents=?, description=?, account_id=?
                WHERE id=? AND deleted_at IS NULL
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    amount.as_float(),
                    amount.cents,
                    payload.description.strip(),
                    account_id,
                    transaction_id,
                ),
            )
        return self.get(transaction_id)

    def delete(self, transaction_id: int):
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE transactions SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (datetime.now(UTC).isoformat(), transaction_id),
            )
        return cursor.rowcount > 0

    def restore(self, transaction_id: int):
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute(
                "SELECT account_id, deleted_at FROM transactions WHERE id=?", (transaction_id,)
            ).fetchone()
            if row is None:
                raise NotFound("Transaction not found")
            if row["deleted_at"] is not None:
                self.resolve_account_id(row["account_id"])
                self.conn.execute("UPDATE transactions SET deleted_at=NULL WHERE id=?", (transaction_id,))
            result = self.get(transaction_id)
        return result

    def history(self, transaction_id: int, limit: int = 100, offset: int = 0):
        if not self.get(transaction_id, include_deleted=True):
            raise NotFound("Transaction not found")
        total = self.conn.execute(
            "SELECT COUNT(*) FROM transaction_audit WHERE transaction_id=?", (transaction_id,)
        ).fetchone()[0]
        rows = self.conn.execute(
            "SELECT * FROM transaction_audit WHERE transaction_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (transaction_id, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["before_state"] = json.loads(item["before_state"]) if item["before_state"] else None
            item["after_state"] = json.loads(item["after_state"])
            items.append(item)
        return {"items": items, "total": total}

    def categories(self):
        return [
            row["category"]
            for row in self.conn.execute(
                "SELECT DISTINCT category FROM transactions WHERE deleted_at IS NULL ORDER BY category"
            )
        ]

    @staticmethod
    def _to_domain(row) -> Transaction:
        return Transaction(
            id=row["id"],
            date=date.fromisoformat(row["date"]),
            type=row["type"],
            category=row["category"],
            amount=Money(row["amount_cents"], row["account_currency"]),
            description=row["description"] or "",
            account_id=row["account_id"],
            account_name=row["account_name"] or "Main Account",
        )
