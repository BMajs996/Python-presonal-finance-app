from .account_repository import AccountRepository
from .balance_repository import BalanceRepository
from .budget_repository import BudgetRepository
from .recurring_repository import RecurringRepository
from .report_repository import ReportRepository
from .transaction_repository import TransactionRepository
from .transfer_repository import TransferRepository


class FinanceRepository:
    """Compatibility facade over feature-owned repositories."""

    def __init__(self, database, base_currency: str = "USD"):
        self.database = database
        connection = database.conn
        self.base_currency = base_currency
        main_currency = connection.execute(
            "SELECT currency FROM accounts WHERE name='Main Account'"
        ).fetchone()["currency"]
        if main_currency != base_currency:
            raise ValueError(
                f"BASE_CURRENCY is {base_currency}, but Main Account uses {main_currency}"
            )
        self.accounts = AccountRepository(connection, base_currency)
        self.balances = BalanceRepository(connection, base_currency)
        self.budgets = BudgetRepository(connection, base_currency)
        self.recurring_transactions = RecurringRepository(connection, base_currency)
        self.reports = ReportRepository(connection, base_currency)
        self.transactions = TransactionRepository(connection, base_currency)
        self.transfers = TransferRepository(connection, base_currency)

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

    def process_recurring_transactions(self):
        return self.recurring_transactions.process_due()

    def close(self):
        self.database.close()
