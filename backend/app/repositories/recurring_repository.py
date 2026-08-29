from datetime import date

from ..domain.money import Money
from ..domain.recurrence import calculate_next_date
from .base_repository import BaseRepository


class RecurringRepository(BaseRepository):
    def list(self):
        return [
            self._serialize(row)
            for row in self.conn.execute(
                """
                SELECT r.*, a.name AS account_name, a.currency AS account_currency
                FROM recurring_transactions r
                LEFT JOIN accounts a ON a.id=r.account_id
                WHERE r.active=1 ORDER BY r.next_date
                """
            )
        ]

    def get(self, recurring_id: int):
        row = self.conn.execute(
            """
            SELECT r.*, a.name AS account_name, a.currency AS account_currency
            FROM recurring_transactions r
            LEFT JOIN accounts a ON a.id=r.account_id
            WHERE r.id=?
            """,
            (recurring_id,),
        ).fetchone()
        return self._serialize(row) if row else None

    def add(self, payload):
        account_id = self.resolve_account_id(payload.account_id)
        amount = Money.from_amount(payload.amount, self.account_currency(account_id))
        next_date = calculate_next_date(payload.frequency, payload.start_date)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO recurring_transactions
                    (type, category, amount, amount_cents, description, frequency,
                     next_date, active, account_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    payload.type,
                    payload.category.strip(),
                    amount.as_float(),
                    amount.cents,
                    payload.description.strip(),
                    payload.frequency,
                    next_date.isoformat(),
                    account_id,
                ),
            )
        return self.get(self.inserted_id(cursor))

    def update(self, recurring_id: int, payload):
        if not self.conn.execute(
            "SELECT id FROM recurring_transactions WHERE id=? AND active=1",
            (recurring_id,),
        ).fetchone():
            return None
        account_id = self.resolve_account_id(payload.account_id)
        amount = Money.from_amount(payload.amount, self.account_currency(account_id))
        with self.conn:
            self.conn.execute(
                """
                UPDATE recurring_transactions
                SET type=?, category=?, amount=?, amount_cents=?, description=?,
                    frequency=?, next_date=?, account_id=?
                WHERE id=?
                """,
                (
                    payload.type,
                    payload.category.strip(),
                    amount.as_float(),
                    amount.cents,
                    payload.description.strip(),
                    payload.frequency,
                    payload.next_date.isoformat(),
                    account_id,
                    recurring_id,
                ),
            )
        return self.get(recurring_id)

    def deactivate(self, recurring_id: int):
        with self.conn:
            self.conn.execute(
                "UPDATE recurring_transactions SET active=0 WHERE id=?",
                (recurring_id,),
            )

    def process_due(self, through: date | None = None):
        through = through or date.today()
        rows = self.conn.execute(
            """
            SELECT id, type, category, amount, amount_cents, description,
                   frequency, next_date, account_id
            FROM recurring_transactions
            WHERE active=1 AND next_date <= ?
            ORDER BY next_date, id
            """,
            (through.isoformat(),),
        ).fetchall()

        with self.conn:
            for row in rows:
                occurrence = date.fromisoformat(row["next_date"])
                guard = 0
                while occurrence <= through:
                    self.conn.execute(
                        """
                        INSERT INTO transactions
                            (date, type, category, amount, amount_cents, description, account_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            occurrence.isoformat(),
                            row["type"],
                            row["category"],
                            row["amount"],
                            row["amount_cents"],
                            f"{row['description']} (Auto)".strip(),
                            row["account_id"] or self.default_account_id(),
                        ),
                    )
                    occurrence = calculate_next_date(row["frequency"], occurrence)
                    guard += 1
                    if guard > 10000:
                        raise RuntimeError(
                            f"Recurring transaction {row['id']} produced too many occurrences."
                        )

                self.conn.execute(
                    "UPDATE recurring_transactions SET next_date=? WHERE id=?",
                    (occurrence.isoformat(), row["id"]),
                )

    @staticmethod
    def _serialize(row):
        amount = Money(row["amount_cents"], row["account_currency"])
        result = dict(row)
        result["amount"] = amount.as_float()
        result["currency"] = amount.currency
        result.pop("amount_cents", None)
        result.pop("account_currency", None)
        return result
