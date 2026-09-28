from ..domain.date_range import DateRange


class ReportService:
    def __init__(self, repository, balance_service):
        self.repository = repository
        self.balance_service = balance_service

    def dashboard(self, days: int = 30):
        period = DateRange.trailing(days)
        data = self.repository.dashboard_data(period)
        data["balance"] = self.balance_service.total()
        data["balance_history"] = self.balance_service.daily_history(period)
        return data

    def monthly(self, months: int = 12):
        data = self.repository.monthly_data(months)
        balances = self.balance_service.monthly_history([item["month"] for item in data["months"]])
        for item in data["months"]:
            item["balance"] = balances[item["month"]]
        return data
