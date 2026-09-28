from ..domain import business_date


class TransferService:
    def __init__(self, repository):
        self.repository = repository

    def list(self, **filters):
        return self.repository.list(**filters)

    def get(self, transfer_id: int):
        return self.repository.get(transfer_id)

    def create(self, payload):
        business_date.require_posted(payload.date)
        return self.repository.add(payload)

    def delete(self, transfer_id: int):
        return self.repository.delete(transfer_id)
