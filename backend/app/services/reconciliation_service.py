from datetime import date

from ..domain.errors import Conflict, InvalidOperation, NotFound
from ..domain.money import Money


class ReconciliationService:
    def __init__(self, repository):
        self.repository = repository

    def accounts(self):
        return self.repository.accounts()

    def list(self, account_id: int):
        return self.repository.list(account_id)

    def detail(self, ident: int):
        statement = self.repository.get(ident)
        entries = self.repository.entries(statement)
        cleared = statement["opening_balance_cents"] + sum(
            entry["amount_cents"] for entry in entries if entry["cleared"]
        )
        return {
            **statement,
            "entries": entries,
            "cleared_balance_cents": cleared,
            "difference_cents": statement["closing_balance_cents"] - cleared,
        }

    def create(self, payload):
        if payload.closing_date > date.today():
            raise InvalidOperation("Statement closing date cannot be in the future")
        closing = Money.from_amount(payload.closing_balance).cents
        if abs(closing) > 9_000_000_000_000_000:
            raise InvalidOperation("Statement balance is too large")
        repo = self.repository
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            repo.resolve_account_id(payload.account_id)
            previous = repo.list(payload.account_id)
            if any(row["status"] == "draft" for row in previous):
                raise Conflict("This account already has a draft statement")
            if previous and payload.closing_date.isoformat() <= previous[0]["closing_date"]:
                raise InvalidOperation("Closing date must be after the last completed statement")
            opening = (
                previous[0]["closing_balance_cents"]
                if previous
                else repo.conn.execute(
                    "SELECT opening_balance_cents FROM accounts WHERE id=?", (payload.account_id,)
                ).fetchone()[0]
            )
            ident = repo.create(payload.account_id, payload.closing_date.isoformat(), opening, closing)
            result = self.detail(ident)
        return result

    def clear(self, ident: int, payload):
        repo = self.repository
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            statement = self.detail(ident)
            if statement["status"] != "draft":
                raise Conflict("Completed statements are read-only")
            repo.resolve_account_id(statement["account_id"])
            if not any(
                row["kind"] == payload.kind and row["entry_id"] == payload.entry_id
                for row in statement["entries"]
            ):
                raise NotFound("Entry is not available for this statement")
            repo.clear(statement, payload.kind, payload.entry_id, payload.cleared)
            result = self.detail(ident)
        return result

    def complete(self, ident: int):
        repo = self.repository
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            statement = self.detail(ident)
            if statement["status"] == "completed":
                return statement
            repo.resolve_account_id(statement["account_id"])
            if statement["difference_cents"] != 0:
                raise Conflict("Statement difference must be zero before completion")
            repo.complete(ident)
            result = self.detail(ident)
        return result

    def cancel(self, ident: int):
        repo = self.repository
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            if repo.get(ident)["status"] != "draft":
                raise Conflict("Completed statements cannot be cancelled")
            repo.cancel(ident)
