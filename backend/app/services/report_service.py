class ReportService:
    def __init__(self, repository):
        self.repository = repository

    def dashboard(self, days: int = 30):
        return self.repository.dashboard(days)

    def monthly(self, months: int = 12):
        return self.repository.monthly(months)
