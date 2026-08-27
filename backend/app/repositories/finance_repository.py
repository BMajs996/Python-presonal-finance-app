from .account_repository import AccountRepository
from .budget_repository import BudgetRepository
from .recurring_repository import RecurringRepository
from .report_repository import ReportRepository
from .transaction_repository import TransactionRepository
from .transfer_repository import TransferRepository


class FinanceRepository:
    """Compatibility facade over feature-owned repositories."""

    def __init__(self, database):
        self.database = database
        connection = database.conn
        self.accounts = AccountRepository(connection)
        self.budgets = BudgetRepository(connection)
        self.recurring_transactions = RecurringRepository(connection)
        self.reports = ReportRepository(connection)
        self.transactions = TransactionRepository(connection)
        self.transfers = TransferRepository(connection)

    def list_transactions(self, *args, **kwargs):
        return self.transactions.list(*args, **kwargs)

    def get_transaction(self, transaction_id):
        return self.transactions.get(transaction_id)

    def add_transaction(self, payload):
        return self.transactions.add(payload)

    def update_transaction(self, transaction_id, payload):
        return self.transactions.update(transaction_id, payload)

    def delete_transaction(self, transaction_id):
        return self.transactions.delete(transaction_id)

    def dashboard(self, days=30):
        return self.reports.dashboard(days)

    def categories(self):
        return self.transactions.categories()

    def list_accounts(self):
        return self.accounts.list()

    def get_account(self, account_id):
        return self.accounts.get(account_id)

    def add_account(self, payload):
        return self.accounts.add(payload)

    def deactivate_account(self, account_id):
        return self.accounts.deactivate(account_id)

    def list_transfers(self, *args, **kwargs):
        return self.transfers.list(*args, **kwargs)

    def get_transfer(self, transfer_id):
        return self.transfers.get(transfer_id)

    def add_transfer(self, payload):
        return self.transfers.add(payload)

    def delete_transfer(self, transfer_id):
        return self.transfers.delete(transfer_id)

    def recurring(self):
        return self.recurring_transactions.list()

    def add_recurring(self, payload):
        return self.recurring_transactions.add(payload)

    def update_recurring(self, recurring_id, payload):
        return self.recurring_transactions.update(recurring_id, payload)

    def delete_recurring(self, recurring_id):
        return self.recurring_transactions.deactivate(recurring_id)

    def get_budget_usage(self):
        return self.budgets.usage()

    def add_budget(self, payload):
        return self.budgets.add(payload)

    def update_budget(self, budget_id, payload):
        return self.budgets.update(budget_id, payload)

    def delete_budget(self, budget_id):
        return self.budgets.delete(budget_id)

    def monthly_report(self, months=12):
        return self.reports.monthly(months)

    def process_recurring_transactions(self):
        return self.recurring_transactions.process_due()

    def close(self):
        self.database.close()
