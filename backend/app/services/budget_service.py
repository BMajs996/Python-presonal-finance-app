class BudgetService:
    def __init__(self, repository):
        self.repository = repository

    def list(self):
        return self.repository.usage()

    def create(self, payload):
        return self.repository.add(payload)

    def update(self, budget_id: int, payload):
        return self.repository.update(budget_id, payload)

    def delete(self, budget_id: int):
        return self.repository.delete(budget_id)
