from ..domain.money import Money


class BalanceService:
    def __init__(self, repository):
        self.repository = repository
        self.currency = repository.base_currency

    def total(self) -> float:
        return Money(self.repository.total_cents(), self.currency).as_float()

    def daily_history(self, days: int):
        running, changes = self.repository.daily_history_cents(days)
        history = []
        for row in changes:
            running += int(row["change_cents"] or 0)
            history.append(
                {
                    "date": row["date"],
                    "balance": Money(running, self.currency).as_float(),
                }
            )
        return history

    def monthly_history(self, labels: list[str]):
        running, changes = self.repository.monthly_history_cents(labels)
        balances = {}
        for label in labels:
            running += changes.get(label, 0)
            balances[label] = Money(running, self.currency).as_float()
        return balances
