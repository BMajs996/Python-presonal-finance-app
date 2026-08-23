class FinanceRepository:
    """Repository boundary around SQLite persistence."""

    def __init__(self, database):
        self.database = database

    def list_transactions(self, *args, **kwargs):
        return self.database.list_transactions(*args, **kwargs)

    def get_transaction(self, transaction_id):
        return self.database.get_transaction(transaction_id)

    def add_transaction(self, payload):
        return self.database.add_transaction(payload)

    def update_transaction(self, transaction_id, payload):
        return self.database.update_transaction(transaction_id, payload)

    def delete_transaction(self, transaction_id):
        return self.database.delete_transaction(transaction_id)

    def dashboard(self, days=30):
        return self.database.dashboard(days)

    def categories(self):
        return self.database.categories()

    def list_accounts(self):
        return self.database.list_accounts()

    def get_account(self, account_id):
        return self.database.get_account(account_id)

    def add_account(self, payload):
        return self.database.add_account(payload)

    def deactivate_account(self, account_id):
        return self.database.deactivate_account(account_id)

    def list_transfers(self, *args, **kwargs):
        return self.database.list_transfers(*args, **kwargs)

    def get_transfer(self, transfer_id):
        return self.database.get_transfer(transfer_id)

    def add_transfer(self, payload):
        return self.database.add_transfer(payload)

    def delete_transfer(self, transfer_id):
        return self.database.delete_transfer(transfer_id)

    def recurring(self):
        return self.database.recurring()

    def add_recurring(self, payload):
        return self.database.add_recurring(payload)

    def update_recurring(self, recurring_id, payload):
        return self.database.update_recurring(recurring_id, payload)

    def delete_recurring(self, recurring_id):
        return self.database.delete_recurring(recurring_id)

    def get_budget_usage(self):
        return self.database.get_budget_usage()

    def add_budget(self, payload):
        return self.database.add_budget(payload)

    def update_budget(self, budget_id, payload):
        return self.database.update_budget(budget_id, payload)

    def delete_budget(self, budget_id):
        return self.database.delete_budget(budget_id)

    def monthly_report(self, months=12):
        return self.database.monthly_report(months)

    def close(self):
        self.database.close()
