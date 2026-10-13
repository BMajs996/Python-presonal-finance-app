from datetime import UTC, datetime

from ..domain import business_date
from ..domain.account import Account
from ..domain.errors import Conflict, InvalidOperation
from ..domain.money import Money
from .base_repository import BaseRepository


class AccountRepository(BaseRepository):
    def list(self, include_inactive: bool = False):
        return self._select(include_inactive=include_inactive)

    def _select(self, *, include_inactive: bool = False, account_id: int | None = None):
        conditions = ["a.user_id=?"]
        if not include_inactive:
            conditions.append("a.active=1")
        cutoff = business_date.today().isoformat()
        params: list[str | int] = [self.user_id]
        if account_id is not None:
            conditions.append("a.id=?")
            params.append(account_id)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([cutoff] * 3)
        # Interpolated clauses are fixed; account IDs remain bound parameters.
        account_sql = f"""
            WITH selected_accounts AS (
                SELECT a.* FROM accounts a {where}
            ), transaction_totals AS (
                SELECT t.account_id,
                       SUM(CASE WHEN t.type='income' THEN t.amount_cents ELSE -t.amount_cents END) net_cents,
                       COUNT(*) transaction_count
                FROM transactions t
                WHERE t.deleted_at IS NULL AND t.date<=?
                  AND t.account_id IN (SELECT id FROM selected_accounts)
                GROUP BY t.account_id
            )
            SELECT a.id, a.name, a.type, a.currency, a.opening_balance_cents, a.active,
                   a.created_at,
                   a.opening_balance_cents
                   + COALESCE(totals.net_cents, 0)
                   + COALESCE((
                       SELECT SUM(t.amount_cents) FROM transfers t WHERE t.to_account_id=a.id AND t.date<=?
                   ), 0)
                   - COALESCE((
                       SELECT SUM(t.amount_cents) FROM transfers t WHERE t.from_account_id=a.id AND t.date<=?
                   ), 0) AS balance_cents,
                   COALESCE(totals.transaction_count,0) AS transaction_count
            FROM selected_accounts a
            LEFT JOIN transaction_totals totals ON totals.account_id=a.id
            ORDER BY a.active DESC, a.name
            """
        rows = self.conn.execute(account_sql, params).fetchall()
        return [self._to_domain(row).to_dict() for row in rows]

    def get(self, account_id: int):
        accounts = self._select(include_inactive=True, account_id=account_id)
        return accounts[0] if accounts else None

    def add(self, payload):
        name = payload.name.strip()
        if not name:
            raise InvalidOperation("Account name is required")
        if payload.currency != self.base_currency:
            raise InvalidOperation(f"Account currency must match the base currency ({self.base_currency})")
        opening_balance = Money.from_amount(payload.opening_balance, payload.currency)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO accounts(
                    name, type, currency, opening_balance, opening_balance_cents, active, created_at, user_id
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?) RETURNING id
                """,
                (
                    name,
                    payload.type,
                    opening_balance.currency,
                    opening_balance.as_float(),
                    opening_balance.cents,
                    datetime.now(UTC).isoformat(),
                    self.user_id,
                ),
            )
            account_id = self.inserted_id(cursor)
        return self.get(account_id)

    def deactivate(self, account_id: int):
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            self.account_currency(account_id)
            if account_id == self.default_account_id():
                raise InvalidOperation("Main Account cannot be deactivated")
            if self.conn.execute(
                "SELECT 1 FROM recurring_transactions WHERE account_id=? AND active=1 LIMIT 1",
                (account_id,),
            ).fetchone():
                raise Conflict("Pause or move active recurring schedules before deactivating this account")
            self.conn.execute(
                "UPDATE accounts SET active=0 WHERE id=? AND user_id=?", (account_id, self.user_id)
            )

    @staticmethod
    def _to_domain(row) -> Account:
        return Account(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            currency=row["currency"],
            opening_balance=Money(row["opening_balance_cents"], row["currency"]),
            balance=Money(int(row["balance_cents"]), row["currency"]),
            active=bool(row["active"]),
            created_at=row["created_at"],
            transaction_count=row["transaction_count"],
        )
