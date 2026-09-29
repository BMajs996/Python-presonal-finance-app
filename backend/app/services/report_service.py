from ..domain.date_range import DateRange


class ReportService:
    def __init__(self, repository, balance_service):
        self.repository = repository
        self.balance_service = balance_service

    def dashboard(self, days: int = 30):
        period = DateRange.trailing(days)
        data = self.repository.dashboard_data(period)
        balance = self.balance_service.total_money()
        data["balance"] = balance.as_float()
        data["money"]["values"]["balance"] = balance.as_decimal_string()
        data["balance_history"] = self.balance_service.daily_history(period)
        return data

    def monthly(self, months: int = 12):
        data = self.repository.monthly_data(months)
        balances = self.balance_service.monthly_history_money([item["month"] for item in data["months"]])
        for item in data["months"]:
            balance = balances[item["month"]]
            item["balance"] = balance.as_float()
            item["money"]["values"]["balance"] = balance.as_decimal_string()
        return data
