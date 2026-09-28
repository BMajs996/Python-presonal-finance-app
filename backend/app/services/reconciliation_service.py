from ..domain import business_date
from ..domain.errors import Conflict, InvalidOperation, NotFound
from ..domain.money import MAX_STATEMENT_BALANCE, Money
from ..reconciliation_schemas import EntryCursor


class ReconciliationService:
    def __init__(self, repository):
        self.repository = repository

    def accounts(self):
        return self.repository.accounts()

    def list(self, account_id: int):
        return self.repository.list(account_id)

    def summary(self, ident: int):
        statement = self.repository.get(ident)
        totals = self.repository.totals(statement)
        cleared = statement["opening_balance_cents"] + totals.pop("cleared_cents")
        return {
            **statement,
            **totals,
            "cleared_balance_cents": cleared,
            "difference_cents": statement["closing_balance_cents"] - cleared,
        }

    def detail(self, ident: int, limit=100, cursor=None):
        statement = self.summary(ident)
        entries = self.repository.entries(statement, limit + 1, cursor)
        next_cursor = None
        if len(entries) > limit:
            last = entries[limit - 1]
            next_cursor = EntryCursor(
                date=last["date"], kind=last["kind"], entry_id=last["entry_id"]
            ).model_dump_json()
        return {**statement, "entries": entries[:limit], "next_cursor": next_cursor}

    def create(self, payload):
        if payload.closing_date > business_date.today():
            raise InvalidOperation("Statement closing date cannot be in the future")
        closing = Money.from_amount(payload.closing_balance, maximum=MAX_STATEMENT_BALANCE).cents
        repo = self.repository
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            repo.resolve_account_id(payload.account_id)
            previous = repo.latest(payload.account_id)
            if repo.has_draft(payload.account_id):
                raise Conflict("This account already has a draft statement")
            if previous and payload.closing_date.isoformat() <= previous["closing_date"]:
                raise InvalidOperation("Closing date must be after the last completed statement")
            opening = (
                previous["closing_balance_cents"]
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
            statement = repo.get(ident)
            if statement["status"] != "draft":
                raise Conflict("Completed statements are read-only")
            repo.resolve_account_id(statement["account_id"])
            if not repo.eligible(statement, payload.kind, payload.entry_id):
                raise NotFound("Entry is not available for this statement")
            repo.clear(statement, payload.kind, payload.entry_id, payload.cleared)
            result = self.summary(ident)
        return result

    def complete(self, ident: int):
        repo = self.repository
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            statement = self.summary(ident)
            if statement["status"] == "completed":
                return self.detail(ident)
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
