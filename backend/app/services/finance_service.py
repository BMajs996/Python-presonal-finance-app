from .account_service import AccountService
from .balance_service import BalanceService
from .budget_service import BudgetService
from .recurring_service import RecurringService
from .report_service import ReportService
from .transaction_service import TransactionService
from .transfer_service import TransferService


class FinanceService:
    """Compatibility facade used by the existing API routes."""

    def __init__(self, repository):
        self.accounts_service = AccountService(repository.accounts)
        self.balance_service = BalanceService(repository.balances)
        self.budgets_service = BudgetService(repository.budgets)
        self.recurring_service = RecurringService(repository.recurring_transactions)
        self.reports_service = ReportService(repository.reports, self.balance_service)
        self.transactions_service = TransactionService(repository.transactions)
        self.transfers_service = TransferService(repository.transfers)

    def dashboard(self, days: int = 30):
        return self.reports_service.dashboard(days)

    def list_transactions(self, **filters):
        return self.transactions_service.list(**filters)

    def create_transaction(self, payload):
        return self.transactions_service.create(payload)

    def get_transaction(self, transaction_id: int):
        return self.transactions_service.get(transaction_id)

    def update_transaction(self, transaction_id: int, payload):
        return self.transactions_service.update(transaction_id, payload)

    def delete_transaction(self, transaction_id: int):
        return self.transactions_service.delete(transaction_id)

    def categories(self):
        return self.transactions_service.categories()

    def accounts(self):
        return self.accounts_service.list()

    def get_account(self, account_id: int):
        return self.accounts_service.get(account_id)

    def create_account(self, payload):
        return self.accounts_service.create(payload)

    def deactivate_account(self, account_id: int):
        return self.accounts_service.deactivate(account_id)

    def transfers(self, **filters):
        return self.transfers_service.list(**filters)

    def get_transfer(self, transfer_id: int):
        return self.transfers_service.get(transfer_id)

    def create_transfer(self, payload):
        return self.transfers_service.create(payload)

    def delete_transfer(self, transfer_id: int):
        return self.transfers_service.delete(transfer_id)

    def recurring(self):
        return self.recurring_service.list()

    def create_recurring(self, payload):
        return self.recurring_service.create(payload)

    def update_recurring(self, recurring_id: int, payload):
        return self.recurring_service.update(recurring_id, payload)

    def delete_recurring(self, recurring_id: int):
        return self.recurring_service.deactivate(recurring_id)

    def budgets(self):
        return self.budgets_service.list()

    def create_budget(self, payload):
        return self.budgets_service.create(payload)

    def update_budget(self, budget_id: int, payload):
        return self.budgets_service.update(budget_id, payload)

    def delete_budget(self, budget_id: int):
        return self.budgets_service.delete(budget_id)

    def monthly_report(self, months: int = 12):
        return self.reports_service.monthly(months)
