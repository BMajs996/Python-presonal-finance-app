# Finance Dashboard

[![CI](https://github.com/BMajs996/Python-presonal-finance-app/actions/workflows/ci.yml/badge.svg)](https://github.com/BMajs996/Python-presonal-finance-app/actions/workflows/ci.yml)

A web dashboard refactor of the personal finance desktop application.

## Stack

- FastAPI backend
- SQLite database
- HTML/CSS/JavaScript frontend
- Chart.js for charts

The backend imports the original desktop SQLite schema and upgrades it automatically with versioned migrations. The archived desktop application must not be used with an upgraded database. Monetary values are persisted as exact integer cents while legacy numeric columns remain available for compatibility.

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
- `DELETE /api/transactions/{id}` (soft delete)
- `GET /api/transactions/deleted?limit=50&offset=0`
- `POST /api/transactions/{id}/restore`
- `GET /api/transactions/{id}/history?limit=50&offset=0`
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

SQLite runs in WAL mode with foreign-key enforcement and a bounded busy timeout. API requests receive
independent database connections that are rolled back and closed at the end of each request. This keeps
concurrent readers responsive and prevents one shared connection from crossing request boundaries. Repository
writes use explicit connection scopes with `IMMEDIATE` transactions and automatic commit or rollback.

## Money constraints and upgrades

Migration 4 validates every money column before installing SQLite insert/update guards. Cent values
must be non-null integers; transaction amounts, recurring amounts, transfer amounts, and budget limits
must be positive. Account opening balances may be zero or negative. Legacy decimal columns must agree
with the cent value divided by 100, so writes cannot silently change only one representation.

These rules are enforced with database triggers, including for direct SQL and separate connections.
The existing tables, IDs, indexes, and foreign keys are preserved; legacy column metadata is unchanged
rather than rebuilt with new NOT NULL declarations. Cents remain the source used for calculations,
and application writes continue supplying both representations.

Create a verified backup before upgrading. If an existing row violates these rules, startup stops with
its table and row ID; migration 4 rolls back its guards and version marker without changing financial
rows. Review and repair the identified data or restore a verified backup before retrying.
Legacy-only writers, including the archived desktop application, cannot write new monetary rows to
an upgraded database without supplying valid matching cent columns.

## Transaction history and recovery

Migration 5 adds a soft-delete timestamp and an append-only transaction history. Transaction creation,
edits, deletion, and restoration record before/after snapshots in the same database transaction as the
financial write. Snapshots retain exact integer cents, account information, and UTC event timestamps.
This includes transactions created by CSV imports and recurring processing.

Each transaction has a History action. Deletion offers an immediate Undo action; the Deleted button
opens retained transactions for recovery after a reload or restart. Restoring preserves the original
transaction ID and amount. Repeated restores do not duplicate entries or audit events. Restoration
requires an active account. Deleted entries cannot be edited and are excluded from active lists,
CSV exports, account balances/counts, budgets, dashboard metrics, and monthly reports.

History starts when the migration is applied; older changes cannot be reconstructed. Existing active
entries and balances are preserved. No-op updates do not create events. The actor is currently
`local`, not an authenticated user identity. SQLite triggers reject audit updates/deletions and
transaction hard deletes, but this is not tamper-proof storage against a database administrator.
There is no automatic purge: deleted financial data and its history remain in the database and backups.

This milestone covers income/expense transactions only. Transfer deletion and other entities retain
their existing behavior; reverting edits is not included. Statement reconciliation is described below.
Create a verified backup before upgrading. Do not run the archived desktop client against schema 5,
because its reads do not understand soft deletion.

## Statement reconciliation

Migration 6 adds saved account statements and cleared-entry associations. The Reconciliation view
accepts an account, statement closing date, and closing balance. Only one draft can exist per account;
its selections persist across reloads. Discarding a draft removes its selections without changing money.
To correct a draft's date or statement balance, discard it and start again.

The first statement starts with the account's configured opening balance; later statements start
with the previous completed statement's closing balance. The remaining difference is:

```text
statement closing balance - (opening balance + selected income - selected expenses
                            + selected incoming transfers - selected outgoing transfers)
```

All calculations and completion checks use integer cents. Select entries that cleared on the statement.
Only active transactions and transfers dated on or before its closing date are eligible. Previously
reconciled entries are excluded; older outstanding entries remain available on later statements.
Transfer sides clear independently for the sending and receiving accounts. Reconciliation never
inserts balance adjustments or changes account totals.

Completion requires an exact zero difference and locks the statement permanently. Dates must not be
in the future and must follow the account's previous completed statement. Completed statements remain
viewable, including for inactive accounts. A selected entry is protected against editing/deletion;
uncheck it in its draft before changing it. Once included in a completed statement, it cannot be
edited or deleted. The account opening balance and currency are also protected after reconciliation
begins. There is no reopen operation in this version; review all selections before completing.

Writes serialize validation and completion with SQLite transactions. Database guards protect selected
transactions/transfers and completed records, including against direct SQL changes through ordinary
connections. Migration preserves existing entries and balances, and backups include reconciliation
history and its locks. These guards are not tamper-proof against a database administrator.

Endpoints:
- `GET /api/reconciliations/accounts` (including inactive accounts)
- `GET /api/reconciliations?account_id={id}`
- `POST /api/reconciliations`
- `GET /api/reconciliations/{id}`
- `PUT /api/reconciliations/{id}/entries` (kind, entry_id, cleared)
- `POST /api/reconciliations/{id}/complete`
- `DELETE /api/reconciliations/{id}` (drafts only)

Create a verified backup before starting the upgraded application. PostgreSQL migration remains deferred.

## API contracts

All JSON success responses have explicit Pydantic response models, including nested dashboard and monthly
report data. The generated OpenAPI contract is available at `/openapi.json` and interactive docs at `/docs`.
Existing `/api` paths, numeric money values, pagination (`items` and `total`), and empty `204` responses
remain compatible with the frontend.

Expected domain failures are handled centrally and return `{"detail": "message"}`: invalid operations
use `400`, missing resources use `404`, and duplicate account names or conflicting budget category updates
use `409`. Request validation retains FastAPI's `422` response with a list in `detail`. Budget and recurring
deletion retain their existing idempotent `204` behavior. Unexpected errors are not converted into client
validation errors, and database constraint details are not exposed in conflict messages.

## Recurring processing

While the server is running, a background task processes due recurring entries immediately and every
60 seconds thereafter. It uses a separate connection and retries failures on the next interval.
Shutdown waits for an active processing pass to finish. Multiple workers can run safely: each pass
locks before reading schedules, and migration 3 adds a unique occurrence ledger keyed by schedule and
due date. The ledger, generated entries, and schedule advancement commit together or roll back together.
Deleting a generated transaction does not delete its occurrence record or cause it to be recreated.

For manual processing or an external scheduler while the server is stopped:

```bash
python -m backend.app.maintenance process-recurring
```

Use `--database PATH` to select a database. The JSON result includes the number of entries created.
Historical generated transactions are preserved without guessed source links; occurrence tracking begins
at each existing schedule's next due date after upgrading. Rewinding schedules into dates processed before
the upgrade can therefore produce duplicates. First due dates and existing month-end rules are unchanged.

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

## Frontend tests

Node.js 22 and the backend development dependencies are required.

```bash
npm ci
npm test
npx playwright install chromium
npm run test:e2e
```

Unit tests cover CSV quoting, output escaping, currency formatting, API errors, and calendar dates in
multiple timezones. Browser tests exercise transaction creation/editing/deletion, CSV preview and export,
transfer neutrality, chart rendering, failed submissions, filter races, transaction history, Undo, and
persistent recovery, and saved statement reconciliation on desktop and emulated mobile Chromium.

Each browser test launches its own real FastAPI server on an ephemeral loopback port with a temporary
database. It does not use your running application or personal finance database. External browser requests
are blocked to verify local chart loading. Set E2E_PYTHON to choose a Python executable; by default the tests
use .venv/bin/python when available, otherwise python from PATH.

Failures retain screenshots and traces in test-results/ and an HTML report in playwright-report/.
Run `npx playwright show-report` to inspect results. CI runs both suites within the required Quality job
and uploads browser diagnostics on failure. All test records are synthetic.

Chart.js 4.5.1 and its license are vendored under frontend/vendor/, so ordinary application startup does
not require Node.js or CDN access. Regenerate those files with `npm run vendor:charts` after an intentional
dependency update and commit them with package-lock.json.
