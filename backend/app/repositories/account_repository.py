from datetime import UTC, datetime

from ..domain.account import Account
from ..domain.money import Money
from .base_repository import BaseRepository


class AccountRepository(BaseRepository):
    def list(self, include_inactive: bool = False):
        where = "" if include_inactive else "WHERE a.active=1"
        # The only interpolated fragment is the fixed active-account clause above.
        account_sql = f"""
            SELECT a.id, a.name, a.type, a.currency, a.opening_balance_cents, a.active,
                   a.created_at,
                   a.opening_balance_cents
                   + COALESCE((
                       SELECT SUM(CASE WHEN t.type='income' THEN t.amount_cents ELSE -t.amount_cents END)
                       FROM transactions t WHERE t.account_id=a.id
                   ), 0)
                   + COALESCE((
                       SELECT SUM(t.amount_cents) FROM transfers t WHERE t.to_account_id=a.id
                   ), 0)
                   - COALESCE((
                       SELECT SUM(t.amount_cents) FROM transfers t WHERE t.from_account_id=a.id
                   ), 0) AS balance_cents,
                   (SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.id) AS transaction_count
            FROM accounts a
            {where}
            ORDER BY a.active DESC, a.name
            """
        rows = self.conn.execute(account_sql).fetchall()
        return [self._to_domain(row).to_dict() for row in rows]

    def get(self, account_id: int):
        return next(
            (row for row in self.list(include_inactive=True) if row["id"] == account_id),
            None,
        )

    def add(self, payload):
        name = payload.name.strip()
        if not name:
            raise ValueError("Account name is required")
        if payload.currency != self.base_currency:
            raise ValueError(f"Account currency must match the base currency ({self.base_currency})")
        opening_balance = Money.from_amount(payload.opening_balance, payload.currency)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO accounts(
                    name, type, currency, opening_balance, opening_balance_cents, active, created_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    name,
                    payload.type,
                    opening_balance.currency,
                    opening_balance.as_float(),
                    opening_balance.cents,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.get(self.inserted_id(cursor))

    def deactivate(self, account_id: int):
        if account_id == self.default_account_id():
            raise ValueError("Main Account cannot be deactivated")
        with self.conn:
            self.conn.execute("UPDATE accounts SET active=0 WHERE id=?", (account_id,))

    @staticmethod
    def _to_domain(row) -> Account:
        return Account(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            currency=row["currency"],
            opening_balance=Money(row["opening_balance_cents"], row["currency"]),
            balance=Money(row["balance_cents"], row["currency"]),
            active=bool(row["active"]),
            created_at=row["created_at"],
            transaction_count=row["transaction_count"],
        )
