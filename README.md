# Finance Dashboard

A web dashboard refactor of the personal finance desktop application.

## Stack

- FastAPI backend
- SQLite database
- HTML/CSS/JavaScript frontend
- Chart.js for charts

The backend keeps the existing SQLite schema compatible with the desktop application and upgrades it automatically with versioned migrations. The current schema adds `accounts`, `transfers`, and account links on transactions/recurring transactions.

## Run locally

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python run.py
```

Open http://127.0.0.1:8000

The database defaults to `data/personal_finance.db`.

## Existing database

Copy your existing `personal_finance.db` into `data/` if you want to use your existing data.

The API creates missing tables but does not delete or reset existing data.

## Project structure

```text
finance-dashboard/
├── backend/
│   ├── app/
│   │   ├── api/              # HTTP routes
│   │   ├── core/             # configuration
│   │   ├── repositories/     # persistence boundary
│   │   ├── services/         # business logic
│   │   ├── database.py       # SQLite implementation
│   │   ├── migrations.py     # versioned schema migrations
│   │   ├── schemas.py        # Pydantic request models
│   │   └── main.py           # FastAPI application
│   ├── tests/
│   ├── requirements.txt
│   └── legacy_desktop.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── data/                     # local DB; *.db is gitignored
├── .github/workflows/
├── pyproject.toml
└── README.md
```

## API

Useful endpoints:

- `GET /api/dashboard`
- `GET /api/transactions`
- `POST /api/transactions`
- `PUT /api/transactions/{id}`
- `DELETE /api/transactions/{id}`
- `GET /api/recurring`
- `POST /api/recurring`
- `DELETE /api/recurring/{id}`
- `GET /api/budgets`
- `POST /api/budgets`
- `DELETE /api/budgets/{id}`
- `GET /api/categories`
- `GET /api/accounts`
- `POST /api/accounts`
- `DELETE /api/accounts/{id}` (deactivates an account)
- `GET /api/transfers`
- `POST /api/transfers`
- `DELETE /api/transfers/{id}`

Swagger documentation is available at `/docs`.

## GitHub

```bash
git init
git add .
git commit -m "Initial finance dashboard"
git branch -M main
git remote add origin <your-github-repository-url>
git push -u origin main
```

## Architecture

The backend is now separated into four layers:

- `api/` — HTTP routes and request/response concerns
- `services/` — application/business logic
- `repositories/` — persistence boundary
- `database.py` — SQLite implementation kept compatible with the existing database
- `core/config.py` — environment-driven configuration

The application uses FastAPI's lifespan API for database startup/shutdown instead of the deprecated `on_event` hooks.

## Development

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
pytest -q
ruff check .
```

The default database remains `data/personal_finance.db`. Override it with `DATABASE_PATH` in a `.env` file when needed.

## Run

```bash
uvicorn backend.app.main:app --reload
```

If you `cd backend` first, use `uvicorn app.main:app --reload` instead. Running
`uvicorn app.main:app --reload` from the repository root will fail with
`ModuleNotFoundError: No module named 'app'`.


## Accounts and transfers

The application now models money across separate accounts. Every transaction is associated with an account; legacy transactions are automatically assigned to `Main Account` during migration so the existing totals remain unchanged.

Transfers are stored separately from transactions. Moving €500 from Checking to Savings therefore changes the two account balances but does not count as €500 of income or expense.

Account balances are calculated as:

```text
opening balance
+ income
- expenses
+ incoming transfers
- outgoing transfers
```

Accounts can be deactivated without deleting their historical transactions. `Main Account` is retained as the compatibility/default account.

## Database migrations

Schema migrations are tracked in `schema_migrations`. On startup the application upgrades older databases automatically. Migration 1 creates accounts/transfers, adds `account_id` to transactions and recurring transactions, creates indexes, and assigns existing records to `Main Account`.

For safety, keep `data/*.db` out of Git. The repository contains no personal financial data.
