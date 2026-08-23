from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .database import FinanceDatabase
from .schemas import (
    BudgetCreate,
    RecurringCreate,
    TransactionCreate,
    TransactionUpdate,
)

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "personal_finance.db"
FRONTEND = BASE_DIR / "frontend"

db = FinanceDatabase(DB_PATH)

app = FastAPI(
    title="Finance Dashboard API",
    version="1.0.0",
    description="Web API for the personal finance dashboard.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(days: int = Query(default=30, ge=1, le=3650)):
    return db.dashboard(days)


@app.get("/api/categories")
def categories():
    return db.categories()


@app.get("/api/transactions")
def transactions(
    search: str = "",
    category: str = "",
    type_: str = Query(default="", alias="type"),
    date_start: str = "",
    date_end: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows, total = db.list_transactions(
        search, category, type_, date_start, date_end, limit, offset
    )
    return {"items": rows, "total": total}


@app.post("/api/transactions", status_code=201)
def create_transaction(payload: TransactionCreate):
    return db.add_transaction(payload)


@app.put("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: int, payload: TransactionUpdate):
    existing = db.get_transaction(transaction_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return db.update_transaction(transaction_id, payload)


@app.delete("/api/transactions/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int):
    if not db.get_transaction(transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete_transaction(transaction_id)


@app.get("/api/recurring")
def recurring():
    return db.recurring()


@app.post("/api/recurring", status_code=201)
def create_recurring(payload: RecurringCreate):
    return db.add_recurring(payload)


@app.delete("/api/recurring/{recurring_id}", status_code=204)
def delete_recurring(recurring_id: int):
    db.delete_recurring(recurring_id)


@app.get("/api/budgets")
def budgets():
    return db.get_budget_usage()


@app.post("/api/budgets", status_code=201)
def create_budget(payload: BudgetCreate):
    return db.add_budget(payload)


@app.delete("/api/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: int):
    db.delete_budget(budget_id)


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/app.js")
def app_js():
    return FileResponse(FRONTEND / "app.js", media_type="application/javascript")


@app.get("/styles.css")
def styles():
    return FileResponse(FRONTEND / "styles.css", media_type="text/css")


@app.on_event("shutdown")
def shutdown():
    db.close()
