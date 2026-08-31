# Finance Dashboard

[![CI](https://github.com/BMajs996/Python-presonal-finance-app/actions/workflows/ci.yml/badge.svg)](https://github.com/BMajs996/Python-presonal-finance-app/actions/workflows/ci.yml)

A web dashboard refactor of the personal finance desktop application.

## Stack

- FastAPI backend
- SQLite database
- HTML/CSS/JavaScript frontend
- Chart.js for charts

The backend keeps the existing SQLite schema compatible with the desktop application and upgrades it automatically with versioned migrations. Monetary values are persisted as exact integer cents while legacy numeric columns remain available for compatibility.

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
│   │   ├── domain/           # framework-free business rules
│   │   ├── repositories/     # feature-owned SQLite queries
│   │   ├── services/         # feature-owned application logic
│   │   ├── database.py       # connection and schema lifecycle
│   │   ├── migrations.py     # versioned schema migrations
│   │   ├── schemas.py        # Pydantic request models
│   │   └── main.py           # FastAPI application
│   ├── tests/
│   ├── requirements-dev.txt
│   ├── requirements.txt
│   └── legacy_desktop.py
├── frontend/
│   ├── api/                  # endpoint-specific clients
│   ├── components/           # reusable charts, tables, modals, and toast
│   ├── utils/                # pure formatting, date, escaping, and CSV helpers
│   ├── views/                # feature-owned UI and event handling
│   ├── index.html
│   ├── app.js                # navigation and application composition
│   └── styles.css
├── data/                     # local DB; *.db is gitignored
├── .github/workflows/
├── pyproject.toml
└── README.md
```

## API

Useful endpoints:

- `GET /api/dashboard?days=30` (period metrics, prior-period comparisons, and balance history)
- `GET /api/transactions`
- `POST /api/transactions`
- `PUT /api/transactions/{id}`
- `DELETE /api/transactions/{id}`
- `GET /api/recurring`
- `POST /api/recurring`
- `PUT /api/recurring/{id}`
- `DELETE /api/recurring/{id}`
- `GET /api/budgets`
- `POST /api/budgets`
- `PUT /api/budgets/{id}`
- `DELETE /api/budgets/{id}`
- `GET /api/reports/monthly`
- `GET /api/categories`
- `GET /api/accounts`
- `POST /api/accounts`
- `DELETE /api/accounts/{id}` (deactivates an account)
- `GET /api/transfers`
- `POST /api/transfers`
- `DELETE /api/transfers/{id}`

Swagger documentation is available at `/docs`.

Currency values use the configured base currency and are formatted in the browser
using the user's locale. Changing the dashboard range updates income, expenses, net,
savings rate, category spending, comparisons, and balance history together.

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

The backend is separated into focused layers:

- `api/` — HTTP routes and request/response concerns
- `services/` — application logic grouped by feature
- `repositories/` — SQLite persistence grouped by feature
- `domain/` — framework-free rules such as recurrence date calculations
- `database.py` — SQLite connection, schema initialization, and migration lifecycle
- `core/config.py` — environment-driven configuration

`FinanceService` and `FinanceRepository` remain as compatibility facades for the current API routes. New
feature code should depend on the focused service or repository instead of adding more methods to those facades.

The application uses FastAPI's lifespan API for database startup/shutdown instead of the deprecated `on_event` hooks.
The frontend uses native browser ES modules served from `/assets`; no bundler or JavaScript framework is required.

## Development

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
ruff check backend/app backend/tests
ruff format --check backend/app backend/tests
mypy backend/app
pytest --cov=backend/app --cov-branch --cov-report=term-missing
pip-audit -r backend/requirements.txt --strict
bandit -q -r backend/app -ll -ii
```

Runtime and development dependencies are pinned to exact versions. CI runs on Python 3.12 and requires
linting, formatting, type checking, JavaScript syntax checking, 80% branch coverage, dependency auditing,
and a Bandit source scan. Dependabot checks Python packages and GitHub Actions weekly.

The default database remains `data/personal_finance.db`. Override it with `DATABASE_PATH` in a `.env` file when needed. Set `BASE_CURRENCY` to a three-letter ISO code before creating a database; it defaults to `USD`.

## Run

```bash
uvicorn backend.app.main:app --reload
```

If you `cd backend` first, use `uvicorn app.main:app --reload` instead. Running
`uvicorn app.main:app --reload` from the repository root will fail with
`ModuleNotFoundError: No module named 'app'`.


## Accounts and transfers

The application now models money across separate accounts. Every transaction is associated with an account; legacy transactions are automatically assigned to `Main Account` during migration so the existing totals remain unchanged.

Transfers are stored separately from transactions. Moving money from Checking to Savings therefore changes the two account balances but does not change income, expenses, global balance, or monthly net worth.

The application uses one configured base currency and rejects accounts in a different currency. This prevents invalid totals that silently add unrelated currencies. Cross-currency accounts will require an explicit exchange-rate model in a future schema.

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

Schema migrations are tracked in `schema_migrations`. On startup the application upgrades older databases automatically. Migration 1 creates accounts/transfers and assigns legacy records to `Main Account`. Migration 2 adds and backfills integer-cent columns for every monetary field without deleting the legacy values.

For safety, keep `data/*.db` out of Git. The repository contains no personal financial data.

## Backup and recovery

Run the maintenance commands from the repository root with the application stopped for restore operations.

```bash
# Verify SQLite pages, foreign keys, and the schema version.
python -m backend.app.maintenance integrity

# Create a timestamped archive in data/backups/.
python -m backend.app.maintenance backup

# Create a backup in a chosen directory or file.
python -m backend.app.maintenance backup /secure/backup/location
python -m backend.app.maintenance backup /secure/finance.financebackup

# Restore after stopping the application. This requires explicit confirmation.
python -m backend.app.maintenance restore /secure/finance.financebackup --yes
```

Use `--database PATH` after the command to operate on a non-default database. Every archive contains a
versioned manifest, database size, schema version, and SHA-256 checksum. Restore verifies those values,
SQLite integrity, foreign keys, and schema compatibility before replacing the database. If the destination
already exists, restore first creates a `pre-restore-*.financebackup` safety archive in `data/backups/`.
If the existing database is corrupted and cannot be archived normally, restore preserves its raw database
and sidecar files as `pre-restore-corrupt-*` forensic copies before replacement.

Test recovery without touching live data:

```bash
python -m backend.app.maintenance restore data/backups/<archive>.financebackup \
  --database /tmp/finance-restore-test.db --yes
python -m backend.app.maintenance integrity --database /tmp/finance-restore-test.db
```

Backup archives contain unencrypted financial data. Store them in an access-controlled or encrypted
location, never commit them, and periodically perform the restore drill above.
