from ..domain.date_range import DateRange


class TransactionService:
    def __init__(self, repository):
        self.repository = repository

    def list(self, **filters):
        date_range = DateRange(
            start=filters.pop("date_start", None),
            end=filters.pop("date_end", None),
        )
        filters["date_start"] = date_range.start_iso
        filters["date_end"] = date_range.end_iso
        return self.repository.list(**filters)

    def get(self, transaction_id: int):
        return self.repository.get(transaction_id)

    def create(self, payload):
        return self.repository.add(payload)

    def update(self, transaction_id: int, payload):
        return self.repository.update(transaction_id, payload)

    def delete(self, transaction_id: int):
        return self.repository.delete(transaction_id)

    def categories(self):
        return self.repository.categories()
