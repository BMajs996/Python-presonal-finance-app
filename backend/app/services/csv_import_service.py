"""Bounded, atomic CSV batches with durable retry receipts."""

import hashlib
import json
from typing import NamedTuple

from ..domain import business_date
from ..domain.errors import Conflict, DomainError, InvalidOperation
from ..domain.money import Money

LOOKUP_BATCH_SIZE = 100


class ImportKey(NamedTuple):
    date: str
    type: str
    amount_cents: int
    category: str
    description: str
    account_id: int


class CsvImportService:
    def __init__(self, repository):
        self.repository = repository

    def _rows(self, rows, write=False):
        repo = self.repository
        default_id = repo.default_account_id() if any(row.account_id is None for row in rows) else None
        account_ids = list({row.account_id if row.account_id is not None else default_id for row in rows})
        accounts = {}
        for start in range(0, len(account_ids), LOOKUP_BATCH_SIZE):
            batch = account_ids[start : start + LOOKUP_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            # Only generated placeholders are interpolated; IDs remain bound parameters.
            query = (
                f"SELECT id,currency FROM accounts WHERE active=1 AND user_id=? AND id IN ({placeholders})"
            )
            accounts.update(
                {row["id"]: row["currency"] for row in repo.conn.execute(query, [repo.user_id, *batch])}
            )
        prepared: list[tuple[ImportKey | None, str | None]] = []
        descriptions: dict[ImportKey, str] = {}
        key: ImportKey | None
        for payload in rows:
            try:
                business_date.require_posted(payload.date)
                account_id = payload.account_id if payload.account_id is not None else default_id
                if account_id is None or account_id not in accounts:
                    raise InvalidOperation(f"Account {account_id} does not exist or is inactive")
                key = ImportKey(
                    payload.date.isoformat(),
                    payload.type,
                    Money.from_amount(payload.amount).cents,
                    payload.category,
                    payload.description.strip().lower(),
                    account_id,
                )
                prepared.append((key, None))
                descriptions.setdefault(key, payload.description.strip())
            except DomainError as exc:
                prepared.append((None, str(exc)))
        existing, stored_descriptions = self._existing(descriptions)
        results = []
        seen = set()
        inserted = set()
        for index, (payload, (key, error)) in enumerate(zip(rows, prepared, strict=True)):
            if error is not None:
                if write:
                    raise Conflict(f"Row {index + 1}: {error}")
                results.append({"status": "invalid", "error": error})
                continue
            assert key is not None
            duplicate = key in seen or key in existing or key in inserted
            seen.add(key)
            if not duplicate and write:
                repo.insert_uncommitted(payload, resolved_account=(key.account_id, accounts[key.account_id]))
                inserted.add(key._replace(description=stored_descriptions[key]))
            results.append({"status": "duplicate" if duplicate else "valid", "error": ""})
        return results

    def _existing(self, descriptions: dict[ImportKey, str]):
        existing: set[ImportKey] = set()
        normalized: dict[ImportKey, str] = {}
        keys = list(descriptions)
        for start in range(0, len(keys), LOOKUP_BATCH_SIZE):
            batch = keys[start : start + LOOKUP_BATCH_SIZE]
            placeholders = ",".join("(?,?,?,?,?,?,?)" for _ in batch)
            # Keep duplicate identity in SQL, including each backend's lower/trim semantics.
            query = f"""WITH candidates(
                date,type,amount_cents,category,description,account_id,raw_description)
                AS (VALUES {placeholders})
                SELECT c.*, lower(trim(c.raw_description)) AS stored_description,
                EXISTS(SELECT 1 FROM transactions t WHERE
                t.date=c.date AND t.type=c.type AND t.amount_cents=c.amount_cents
                AND t.category=c.category AND lower(trim(t.description))=c.description
                AND t.account_id=c.account_id AND t.deleted_at IS NULL) AS duplicate
                FROM candidates c"""
            params = [value for key in batch for value in (*key, descriptions[key])]
            for row in self.repository.conn.execute(query, params):
                key = ImportKey(*(row[column] for column in ImportKey._fields))
                normalized[key] = row["stored_description"]
                if row["duplicate"]:
                    existing.add(key)
        return existing, normalized

    def preview(self, rows):
        return {"rows": self._rows(rows)}

    def commit(self, payload):
        repo = self.repository
        for row in payload.rows:
            business_date.require_posted(row.date)
        serialized = json.dumps([row.model_dump(mode="json") for row in payload.rows], sort_keys=True)
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        # Preserve bootstrap owner's existing retry receipts without exposing them to another user.
        prefix = "csv-import:" if repo.user_id == 1 else f"user:{repo.user_id}:csv-import:"
        key = prefix + str(payload.batch_id)
        with repo.conn:
            repo.conn.execute("BEGIN IMMEDIATE")
            receipt = repo.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if receipt:
                saved = json.loads(receipt["value"])
                if saved["fingerprint"] != fingerprint:
                    raise Conflict("This import ID was already used for different rows")
                return saved["result"]
            rows = self._rows(payload.rows, write=True)
            result = {
                "imported": sum(row["status"] == "valid" for row in rows),
                "duplicates": sum(row["status"] == "duplicate" for row in rows),
            }
            repo.conn.execute(
                "INSERT INTO settings(key,value) VALUES (?,?)",
                (key, json.dumps({"fingerprint": fingerprint, "result": result})),
            )
        return result
