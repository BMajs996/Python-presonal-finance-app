class RecurringService:
    def __init__(self, repository):
        self.repository = repository

    def list(self):
        return self.repository.list()

    def create(self, payload):
        return self.repository.add(payload)

    def update(self, recurring_id: int, payload):
        return self.repository.update(recurring_id, payload)

    def deactivate(self, recurring_id: int):
        return self.repository.deactivate(recurring_id)

    def process_due(self):
        return self.repository.process_due()
