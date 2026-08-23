class FinanceService:
    """Application/business layer. Keeps HTTP concerns out of persistence."""

    def __init__(self, repository):
        self.repository = repository

    def dashboard(self, days: int = 30):
        return self.repository.dashboard(days)

    def list_transactions(self, **filters):
        return self.repository.list_transactions(**filters)

    def create_transaction(self, payload):
        return self.repository.add_transaction(payload)

    def get_transaction(self, transaction_id: int):
        return self.repository.get_transaction(transaction_id)

    def update_transaction(self, transaction_id: int, payload):
        return self.repository.update_transaction(transaction_id, payload)

    def delete_transaction(self, transaction_id: int):
        return self.repository.delete_transaction(transaction_id)

    def categories(self):
        return self.repository.categories()

    def accounts(self):
        return self.repository.list_accounts()

    def get_account(self, account_id: int):
        return self.repository.get_account(account_id)

    def create_account(self, payload):
        return self.repository.add_account(payload)

    def deactivate_account(self, account_id: int):
        return self.repository.deactivate_account(account_id)

    def transfers(self, **filters):
        return self.repository.list_transfers(**filters)

    def get_transfer(self, transfer_id: int):
        return self.repository.get_transfer(transfer_id)

    def create_transfer(self, payload):
        return self.repository.add_transfer(payload)

    def delete_transfer(self, transfer_id: int):
        return self.repository.delete_transfer(transfer_id)

    def recurring(self):
        return self.repository.recurring()

    def create_recurring(self, payload):
        return self.repository.add_recurring(payload)

    def delete_recurring(self, recurring_id: int):
        return self.repository.delete_recurring(recurring_id)

    def update_recurring(self, recurring_id: int, payload):
        return self.repository.update_recurring(recurring_id, payload)

    def budgets(self):
        return self.repository.get_budget_usage()

    def create_budget(self, payload):
        return self.repository.add_budget(payload)

    def update_budget(self, budget_id: int, payload):
        return self.repository.update_budget(budget_id, payload)

    def delete_budget(self, budget_id: int):
        return self.repository.delete_budget(budget_id)

    def monthly_report(self, months: int = 12):
        return self.repository.monthly_report(months)
