import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import (
    accounts,
    auth,
    budgets,
    dashboard,
    reconciliation,
    recurring,
    reports,
    transactions,
    transfers,
)
from .api.errors import register_error_handlers
from .core.auth_middleware import ConfiguredCORS, ConfiguredHosts, OwnerAccessMiddleware
from .core.config import settings
from .database_factory import open_database
from .frontend_assets import frontend_page, frontend_revision
from .schemas import HealthResponse
from .services.auth_service import initialize_auth
from .services.recurring_runner import run_recurring


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = open_database(settings)
    initialize_auth(database)
    database.close()
    app.state.database = database
    stop = asyncio.Event()
    runner = asyncio.create_task(run_recurring(database, stop))
    try:
        yield
    finally:
        stop.set()
        await runner


asset_revision = frontend_revision(settings.frontend_path)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Web API for the personal finance dashboard.",
    lifespan=lifespan,
)

register_error_handlers(app)

app.add_middleware(OwnerAccessMiddleware)
app.add_middleware(ConfiguredCORS)
app.add_middleware(ConfiguredHosts)
app.include_router(auth.router)

app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(transactions.router)
app.include_router(recurring.router)
app.include_router(budgets.router)
app.include_router(reports.router)
app.include_router(reconciliation.router)


@app.get("/api/health", tags=["system"], response_model=HealthResponse)
def health():
    return {"status": "ok"}


@app.get("/login", include_in_schema=False)
def login_page():
    return frontend_page(settings.frontend_path, "login.html", asset_revision)


@app.get("/")
def index():
    return frontend_page(settings.frontend_path, "index.html", asset_revision)


app.mount(f"/assets/{asset_revision}", StaticFiles(directory=settings.frontend_path), name="frontend-release")
app.mount("/assets", StaticFiles(directory=settings.frontend_path), name="frontend-assets")
