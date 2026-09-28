"""Bounded, atomic CSV batches with durable retry receipts."""

import hashlib
import json

from ..domain import business_date
from ..domain.errors import Conflict, DomainError
from ..domain.money import Money


class CsvImportService:
    def __init__(self, repository):
        self.repository = repository

    def _rows(self, rows, write=False):
        repo = self.repository
        results = []
        seen = set()
        for index, payload in enumerate(rows):
            try:
                business_date.require_posted(payload.date)
                account_id = repo.resolve_account_id(payload.account_id)
            except DomainError as exc:
                if write:
                    raise Conflict(f"Row {index + 1}: {exc}") from exc
                results.append({"status": "invalid", "error": str(exc)})
                continue
            cents = Money.from_amount(payload.amount).cents
            key = (
                payload.date.isoformat(),
                payload.type,
                cents,
                payload.category.strip().lower(),
                payload.description.strip().lower(),
                account_id,
            )
            duplicate = (
                key in seen
                or repo.conn.execute(
                    """SELECT 1 FROM transactions WHERE deleted_at IS NULL
                AND date=? AND type=? AND amount_cents=? AND lower(trim(category))=?
                AND lower(trim(description))=? AND account_id=? LIMIT 1""",
                    key,
                ).fetchone()
                is not None
            )
            seen.add(key)
            if not duplicate and write:
                repo.insert_uncommitted(payload)
            results.append({"status": "duplicate" if duplicate else "valid", "error": ""})
        return results

    def preview(self, rows):
        return {"rows": self._rows(rows)}

    def commit(self, payload):
        repo = self.repository
        for row in payload.rows:
            business_date.require_posted(row.date)
        serialized = json.dumps([row.model_dump(mode="json") for row in payload.rows], sort_keys=True)
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        key = "csv-import:" + str(payload.batch_id)
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
