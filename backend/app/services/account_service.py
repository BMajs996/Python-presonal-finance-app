class AccountService:
    def __init__(self, repository):
        self.repository = repository

    def list(self):
        return self.repository.list()

    def get(self, account_id: int):
        return self.repository.get(account_id)

    def create(self, payload):
        return self.repository.add(payload)

    def deactivate(self, account_id: int):
        return self.repository.deactivate(account_id)
