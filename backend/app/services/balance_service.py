from datetime import timedelta

from ..domain.date_range import DateRange
from ..domain.money import Money, money_contract


class BalanceService:
    def __init__(self, repository):
        self.repository = repository
        self.currency = repository.base_currency

    def total_money(self) -> Money:
        return Money(self.repository.total_cents(), self.currency)

    def total(self) -> float:
        return self.total_money().as_float()

    def daily_history(self, period: DateRange):
        days = period.days
        assert period.start is not None
        running, changes = self.repository.daily_history_cents(period)
        changes_by_date = {row["date"]: int(row["change_cents"] or 0) for row in changes}
        history = []
        for offset in range(days):
            label = (period.start + timedelta(days=offset)).isoformat()
            running += changes_by_date.get(label, 0)
            history.append(
                {
                    "date": label,
                    "balance": Money(running, self.currency).as_float(),
                    "money": money_contract(self.currency, balance=running),
                }
            )
        return history

    def monthly_history_money(self, labels: list[str]):
        running, changes = self.repository.monthly_history_cents(labels)
        balances = {}
        for label in labels:
            running += changes.get(label, 0)
            balances[label] = Money(running, self.currency)
        return balances

    def monthly_history(self, labels: list[str]):
        return {label: value.as_float() for label, value in self.monthly_history_money(labels).items()}
