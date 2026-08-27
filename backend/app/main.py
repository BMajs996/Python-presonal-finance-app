from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .api import accounts, budgets, dashboard, recurring, reports, transactions, transfers
from .core.config import settings
from .database import FinanceDatabase
from .repositories.finance_repository import FinanceRepository
from .services.finance_service import FinanceService


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = FinanceDatabase(settings.database_path)
    repository = FinanceRepository(database)
    repository.process_recurring_transactions()
    app.state.database = database
    app.state.finance_service = FinanceService(repository)
    try:
        yield
    finally:
        database.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Web API for the personal finance dashboard.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(transactions.router)
app.include_router(recurring.router)
app.include_router(budgets.router)
app.include_router(reports.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(settings.frontend_path / "index.html")


@app.get("/app.js")
def app_js():
    return FileResponse(settings.frontend_path / "app.js", media_type="application/javascript")


@app.get("/styles.css")
def styles():
    return FileResponse(settings.frontend_path / "styles.css", media_type="text/css")
