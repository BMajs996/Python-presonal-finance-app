# Finance Dashboard

[![CI](https://github.com/BMajs996/Python-presonal-finance-app/actions/workflows/ci.yml/badge.svg)](https://github.com/BMajs996/Python-presonal-finance-app/actions/workflows/ci.yml)

A web dashboard refactor of the personal finance desktop application.

## Stack

- FastAPI backend
- PostgreSQL 18 or SQLite database
- HTML/CSS/JavaScript frontend
- Chart.js for charts

The backend imports the original desktop SQLite schema and upgrades it automatically with versioned migrations. The archived desktop application must not be used with an upgraded database. Monetary values are persisted as exact integer cents while legacy numeric columns remain available for compatibility.

## Run locally

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
python -m backend.app.setup_owner
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
│   │   ├── repositories/     # feature-owned database queries
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
- `repositories/` — database persistence grouped by feature
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

Accounts can be deactivated without deleting their historical transactions, but active recurring schedules
must first be deactivated (paused) or moved to another active account. Otherwise the API returns
`409 Conflict`. The check and deactivation share the same writer reservation as recurring processing
on both SQLite and PostgreSQL. `Main Account` cannot be deactivated.

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

Create a verified backup before starting the upgraded application. PostgreSQL migration is available using the procedure below.

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


## PostgreSQL

SQLite remains the default when `DATABASE_URL` is unset. Setting the URL selects PostgreSQL
for API requests and recurring processing; it takes precedence over `DATABASE_PATH`.
The app remains single-currency. Keep `BASE_CURRENCY` unchanged when moving existing data.

Install PostgreSQL 18 and its client tools using your operating system's package manager.
On a Linux installation with peer authentication, create a role matching your login and two databases.
For the local login `taraba`, run each complete command:

```bash
sudo --user=postgres createuser taraba
sudo --user=postgres createdb --owner=taraba finance_dashboard
sudo --user=postgres createdb --owner=taraba finance_dashboard_test
```

The application role does not need superuser or database-creation privileges.
Enter administrator passwords only in the terminal, never in configuration or source control.
A local Unix socket URL needs no database password.

### Move existing SQLite data

Stop all application servers and recurring schedulers before starting. Install the updated dependencies.
The destination must be empty: do not launch the app against PostgreSQL before importing.

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
export DATABASE_URL=postgresql:///finance_dashboard

# Dry run: copy and compare every column, then roll back the destination.
python -m backend.app.maintenance migrate-postgres --database data/personal_finance.db

# Creates a verified pre-postgres backup, verifies the copy, and commits atomically.
python -m backend.app.maintenance migrate-postgres --database data/personal_finance.db --yes
```

The transfer preserves IDs, exact cents, deleted transactions, audit history, recurring occurrence
records, and completed reconciliations. It blocks SQLite writers during the transfer and leaves
the original database untouched. A failed transfer rolls back the destination; an occupied
destination is refused. Older supported SQLite schemas are upgraded only in a temporary snapshot.

After success, put `DATABASE_URL=postgresql:///finance_dashboard` in the gitignored `.env`,
then run `python run.py`. Do not restart old SQLite writers. Before any new PostgreSQL writes,
you can roll back by stopping the app and clearing `DATABASE_URL`. After new writes,
switching back would lose those changes; reconcile/export them first.

PostgreSQL schema versions are tracked separately in `postgres_schema_migrations`.
Version 1 implements SQLite schema 6 semantics. The historical SQLite migration ledger is preserved.
PostgreSQL uses BIGINT cents, foreign keys, money constraints, and audit/reconciliation triggers.
An advisory transaction lock currently serializes writers to preserve existing financial invariants.
This is deliberately conservative, not a claim of high write scalability.

### PostgreSQL backup and recovery

The SQLite `backup`, `restore`, and `integrity` commands do not operate on PostgreSQL.
With `DATABASE_URL` set, they require an explicit SQLite `--database` path.
Use PostgreSQL's native tools for the active database:

```bash
mkdir -p data/backups
chmod 700 data/backups
pg_dump --dbname=finance_dashboard --format=custom --no-owner --no-privileges \
  --file="data/backups/finance-$(date +%Y%m%d-%H%M%S).pgdump"
```

Recovery drill: ask the administrator to create a separate empty database owned by your login,
then restore a trusted dump there, never over the live database:

```bash
sudo --user=postgres createdb --owner=taraba finance_dashboard_restore
pg_restore --dbname=finance_dashboard_restore --single-transaction --exit-on-error \
  --no-owner --no-privileges data/backups/<archive>.pgdump
```

Compare account balances, reports, history, and reconciliation records before any cutover.
Stop the app before changing its URL to a restored database. Dumps contain unencrypted financial
data and database code; protect them, never commit them, and restore only trusted archives.
See the [PostgreSQL pg_dump documentation](https://www.postgresql.org/docs/18/app-pgdump.html).

### Test both backends

```bash
TEST_DATABASE_URL=postgresql:///finance_dashboard_test pytest --cov=backend/app --cov-branch
npm run test:e2e
E2E_DATABASE_URL=postgresql:///finance_dashboard_test npm run test:e2e
```

PostgreSQL tests require a database name ending in `_test`; each uses its own temporary schema.
They never truncate the database or use the live application URL. Without `TEST_DATABASE_URL`,
PostgreSQL backend tests are skipped. Browser tests default to temporary SQLite databases.
CI supplies PostgreSQL 18 and exercises both backends.


## Single-owner access

All financial API routes and API documentation require an owner session. There is no registration,
anonymous mode, or multi-user sharing. Existing financial records belong to this one owner.

From the repository root, set or reset the password using hidden terminal prompts:

```bash
source .venv/bin/activate
python -m backend.app.setup_owner
python run.py
```

The default username is `owner`; override it with `OWNER_USERNAME`. Passwords must be 15-1024
characters. Only an Argon2id hash is written to the private `.env`, preserving other settings.
Restart every app worker after changing credentials. Changing the username or password hash
invalidates existing sessions. There is no web password-reset endpoint; server access is required.
Without an owner hash, local startup is allowed but financial access remains locked.

Sessions use random opaque HttpOnly, SameSite=Strict cookies. Only token hashes are stored in
the database, with an eight-hour absolute lifetime and 30-minute idle timeout by default.
Sign-out revokes the server-side session. Sessions and the login attempt counter are shared
across workers in three additive operational tables, independent of financial schema versions.
Each client address is limited to ten login attempts per minute, with a global ceiling of 100;
successful attempts also count. At most two password hashes run concurrently per app worker;
excess concurrent attempts receive a short 429 response. Retry-After reports the remaining
window for rate limits. Forwarded address
headers are not read directly by the application: only a correctly configured trusted proxy
may supply the client address. Distributed attacks can still reach the global ceiling;
add edge rate limiting before public deployment.

Session checks normally read without a write transaction. Activity timestamps update at most
once per minute (or one quarter of a shorter configured idle timeout). Idle expiry can therefore
occur up to that interval before the last request. A busy database can defer activity updates
further: these best-effort writes never extend absolute expiry or recreate a revoked session.
PostgreSQL authentication writes use a separate advisory lock from financial writes.

Write requests require both an exact allowed Origin and a session-bound `X-CSRF-Token`.
Login requires an allowed Origin but no existing session. `GET /api/auth/session` returns the
CSRF token to authenticated clients; the frontend keeps it in memory, not local storage.
Authentication responses and private pages/API responses are marked no-store.

### Origins and production

Development defaults permit only `http://127.0.0.1:8000` and `http://localhost:8000`.
Changing the port requires updating `CORS_ORIGINS`. Use comma-separated origins without paths
or trailing slashes; wildcards, null origins and embedded credentials are rejected.
CORS permits credentials, GET/POST/PUT/DELETE, Content-Type and X-CSRF-Token.
CORS is a browser policy, not a replacement for authentication or CSRF validation.

Before public deployment, configure:

```dotenv
ENVIRONMENT=production
CORS_ORIGINS=https://finance.example.com
OWNER_USERNAME=owner
```

Production startup requires an owner hash and HTTPS-only origins, enables Secure cookies,
and rejects requests whose trusted ASGI scheme is not HTTPS. This rejection cannot protect
credentials already sent over plaintext; TLS must terminate at the public edge.
Serve the UI and API from the same origin over HTTPS through a trusted reverse proxy.
Cross-site frontend hosting is not supported by the Strict session cookie.
Keep PostgreSQL private and do not use development reload in production.

Database dumps can contain session records. When restoring, rotate the owner password before
exposing the restored app so previously issued sessions cannot become valid again.
SQLite-to-PostgreSQL migration intentionally omits these operational auth tables: financial data
is verified as before, while sessions and login counters start fresh on the destination.
Keep the owner hash configured separately; it is not part of a database backup.

The security design follows [OWASP session management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
and [password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).


## Pre-launch hardening

The review fixes are developed on `feature/prelaunch-hardening`. Deployment is not yet approved:
the external checks below still require a real hosting target.

### Data handling

- Transactions, recurring amounts, transfers and budget limits are at most 1,000,000,000.00
  in the base currency. Opening balances allow the same positive/negative range.
  NaN, infinity and excessive magnitudes are rejected before cent conversion.
  Computed totals are not restricted by this per-entry limit. Statement balances retain
  their separate +/-90,000,000,000,000.00 limit because they represent aggregates.
- Recurring processing commits at most 100 occurrences per schedule per pass, then visits
  the next schedule. Remaining backlog is processed on later scheduled/manual passes.
  Occurrence uniqueness and atomic per-schedule batches prevent duplicate or partial batches.
  Recurring start/next dates must be between 1900-01-01 and 9998-12-31.
- Reconciliation detail returns 100 entries by default, at most 200 with `limit`.
  Pass the returned `next_cursor` unchanged as `cursor` for the next page. Totals cover
  the entire statement, not just its displayed page. Clear mutations return summary/totals,
  not ledger rows. The frontend preserves the current page and provides Previous/Next.
- CSV files are limited to 2 MiB and 1,000 transactions before preview. Server preview and
  import endpoints also cap batches at 1,000 rows. Preview checks only candidate duplicates,
  not the complete transaction history. Keys include date, type, exact cents, category,
  description and account. Category matching uses exact stored text; description comparisons
  retain their trimmed/lowercase rule. Likely duplicates are skipped.
- `POST /api/transactions/import/preview` accepts `{"rows": [...]}`.
  `POST /api/transactions/import` accepts `{"batch_id": "<uuid>", "rows": [...]}`.
  A batch commits financial rows, audit events and its retry receipt atomically. Retrying
  the same ID and payload returns its original result; changing the payload for a used ID
  returns 409. Receipts use namespaced `csv-import:` keys in the existing settings table,
  persist in backups/migrations, and should not be manually deleted while retries are possible.
  A validation/write failure leaves no partial import. The preview remains available to retry.
- Browser CSV exports are bounded to 10,000 rows; narrow filters for larger histories.
  Exported text beginning with optional whitespace followed by `=`, `+`, `-` or `@`
  is prefixed with an apostrophe; numeric amount/ID columns stay numeric.
  This changes export text only, not database values. Reimport preserves the protective apostrophe.
  Verify behavior in your target spreadsheet; editing/re-saving can remove spreadsheet protections.
- Legacy date/type text is escaped when rendered and transaction CSS classes are allowlisted.
  A same-origin Content-Security-Policy is currently **report-only**, not an enforcement claim.
  Review browser policy violations on staging before switching to enforcement.
- Monthly report predicates compare ISO dates directly rather than wrapping indexed date
  columns in `substr`. Grouping still uses month labels; report totals sum integer cents.

### Deployment gates still open

1. Terminate TLS at a trusted reverse proxy, redirect public HTTP to HTTPS, and bind the app
   to loopback/private networking. Block public access to the backend and PostgreSQL ports.
2. Trust forwarded headers only from that proxy's exact addresses, never a wildcard.
   Verify real client-address throttling and HTTPS scheme propagation through the actual proxy.
3. Verify TLS and redirects externally, then enable HSTS at the edge with an appropriate
   rollout policy. Do not enable includeSubDomains/preload without reviewing every subdomain.
4. Collect CSP violations during staging and enforce the tested policy. Review any legacy
   malformed dates/types before introducing stricter database guards.
5. Run a backup/restore drill and compare balances, reports, history and reconciliations
   on an isolated restored database. Rotate owner credentials before exposing a restored app.
6. Measure connection counts and query plans on deployment-sized data. PostgreSQL still uses
   per-operation connections; a bounded pool remains a capacity improvement to evaluate.
   Statement history itself remains unpaginated; ledger entry pages are bounded.


## FIN-01: Inactive accounts and recurring schedule repair

The worker checks the referenced account inside each schedule's writer transaction. A due schedule
with an inactive or missing account is paused (`active=0`) and emits one warning containing only
the schedule ID and a fixed reason. It creates no transaction, audit event, or occurrence claim,
and leaves `account_id` and `next_date` unchanged. Later passes skip the paused schedule.
Creating or editing a schedule validates its account under the same writer reservation.
No worker path silently assigns a legacy schedule or its entries to Main Account.

### Owner-reviewed repair

1. Back up the database. Run the following read-only query against the configured backend
   using a trusted local SQL client. It includes future schedules and schedules already
   paused by the worker, not just currently due work:

   ```sql
   SELECT r.id, r.account_id, r.active AS schedule_active, r.next_date,
          a.active AS account_active
   FROM recurring_transactions r
   LEFT JOIN accounts a ON a.id = r.account_id
   WHERE a.id IS NULL OR a.active <> 1
   ORDER BY r.id;
   ```

2. Have the owner review the returned IDs before bulk or manual repairs. For an active
   schedule on an inactive account, use the Recurring view's Deactivate action
   (`DELETE /api/recurring/{id}`) to pause it, or Edit to select an explicitly approved
   active account (`PUT /api/recurring/{id}`). Apply only the reviewed IDs.
   Pausing is idempotent and works for missing-account schedules through the API as well.

3. Schedules already paused by the worker remain paused. The current UI cannot reactivate
   them. Keep the original record for traceability; after owner approval, create a replacement
   on the chosen active account with an explicitly reviewed first occurrence. Creation
   schedules the first occurrence one interval after its start date. Avoid accidental
   historical catch-up or duplicate replacement schedules.

4. Re-run the query and confirm no unreviewed active schedules remain on inactive/missing
   accounts. Inspect any transactions created before this fix separately; this repair does
   not move, delete, or rewrite historical entries or occurrence claims. Historical
   reassignment or correction requires a separate owner-approved decision.

No bulk repair of the live database is performed by installing this code. The worker's
automatic pause is a defensive stop, not approval to reassign or resume a schedule.


## FIN-02: Dashboard balance chart period

The dashboard computes one inclusive trailing range: `start = end - (days - 1)`,
with `end` captured once as the server's current date. Period income, expenses,
category totals and balance history use those same boundaries.

The balance chart shows a daily closing balance for every calendar day in the returned
period, including today and days with no transactions. Its opening balance combines
account opening balances and non-deleted transactions strictly before `start`.
Those earlier transactions do not become chart points. Transactions after `end`
are excluded from the chart and period summary. Transfers remain globally neutral.

## FIN-03: Posted-only ledger

Manual transactions and transfers cannot be dated after the server's business date.
API create/edit, CSV import and transaction recovery enforce this rule; browser date
limits are supplementary. CSV preview marks future rows invalid. Plan future activity
using recurring schedules, which only post occurrences through the business date.

The business date uses the configured IANA timezone, captured once per request.
Configure `BUSINESS_TIMEZONE` deliberately (default: `Europe/Belgrade`). Forms obtain their date limit from
the authenticated `/api/ledger-policy` endpoint, not the browser's timezone.

Existing future entries are preserved, but excluded from posted balances, account
cards, charts, reports, budget usage, normal transaction lists/exports and transfer
lists until their date arrives. Future transfers affect neither account early.
Advancing the date includes existing entries without inserting them again. Current
month reports show posted activity to date, not a forecast.

### Review existing future entries

Before rollout, back up the database and run this read-only inventory:

```bash
python -m backend.app.maintenance review-future --limit 100 --offset 0
```

It uses the configured database without initialization or migrations, and returns
the business date, total count and entry/account IDs. Increase `--offset` to inspect
remaining pages. Use `--database /path/to/database.db` to review a specific SQLite
database instead of the configured PostgreSQL database.

Have the owner review each result. Correct a transaction's date only if it actually
posted on that date, or delete it after approval. A future transfer can be deleted
and recreated with its verified actual date. Retain records intentionally awaiting
their date, or replace planned activity with an owner-approved recurring schedule.
Do not silently backdate, reassign, delete or duplicate financial entries. Deleted
transaction history remains available, but future entries cannot be restored early.


## FIN-04: Business timezone

Set `BUSINESS_TIMEZONE=Europe/Belgrade` in the app environment. This explicit default
is independent of the host's timezone; a UTC-hosted server follows the same financial
calendar. Other installed IANA names, such as `UTC`, are supported. Invalid names or
missing timezone data stop startup with a configuration error rather than falling
back to host time. Deployment images must provide system IANA timezone data
(`tzdata` on Debian/Ubuntu); verify this before starting the app.

The clock reads an aware UTC instant and converts it with `zoneinfo.ZoneInfo`.
One business date is captured per HTTP request, recurring-processing pass, and
future-entry review. A pass spanning midnight keeps its original date; the next
pass advances. Daylight-saving changes do not duplicate a recurring occurrence.
Reports, budgets, balances, CSV and future-date validation, and reconciliation
all use this financial calendar.

The authenticated `/api/ledger-policy` endpoint returns `business_date`,
`business_timezone`, and the ledger model. Financial forms refresh server date
metadata when opened; reconciliation refreshes when its view loads. Dashboard
period labels use returned boundaries, not the browser timezone. A form left open
through midnight still receives authoritative backend validation when submitted.

Audit, backup, and deletion timestamps remain UTC. Session expiry remains absolute
time. Stored transaction dates are calendar dates and are not shifted or rewritten.
No database schema migration or automatic financial-data repair is performed.

Before rollout, confirm the timezone with the owner, set the environment for both
web and maintenance processes, restart them, and verify the ledger-policy response.
Changing the timezone later can change which date-based entries are currently
effective; review that operational change rather than treating it as cosmetic.


## DATA-01: Category identity and owner-reviewed migration

This release is the **review-first stage**, not a category-ID migration.
Transaction, recurring and budget inputs trim leading/trailing Unicode whitespace
and reject blank names. Case, internal whitespace and Unicode spelling otherwise
remain significant. Budgets, report grouping, filters and CSV category matching all
use that exact stored text. For example, `Food`, `food`, and `FOOD` remain separate;
new input ` Food ` is stored as `Food`. Existing historical text is never rewritten.

CSV duplicates require the same date, type, integer-cent amount, exact category,
account, and the existing trimmed/lowercase description comparison. Category case
or internal-whitespace variants are no longer silently skipped as duplicates.
Existing import batch receipts remain idempotent; retrying an old batch returns its
original result rather than applying new rules to it.

Run the read-only collision inventory before planning category-ID migration:

```bash
python -m backend.app.maintenance review-categories --limit 100 --offset 0
```

Use `--database /path/to/database.db` to select SQLite instead of configured
PostgreSQL. The command never initializes, migrates, or writes the database.
It uses a consistent read snapshot and includes active/inactive recurring schedules,
deleted and non-deleted transactions (including future dates), and all budget months.

The candidate key policy `nfc-whitespace-casefold-v1` applies NFC normalization,
collapses Unicode whitespace runs to one ASCII space while removing edge whitespace,
applies Unicode case folding, and normalizes to NFC again. It deliberately does not
apply compatibility normalization (NFKC), remove accents, or merge look-alike characters.
This key is **only a review signal**, not current financial identity. The report
records Python's Unicode database version so reviews can detect runtime differences.

Results include candidate collisions and per-variant usage, plus reconciliation
baselines: row counts and exact cent strings grouped by source, currency, type and
state/month. Transaction amounts, budget limits, and recurring amounts are kept
separate; they must not be added together as one financial total.

Next migration gate: back up the database, save this baseline, obtain owner-approved
mappings from exact names to stable category IDs/display names, and explicitly resolve
conflicting budget limits. Test the mapping on an isolated restored database, reconcile
counts and cents by source/currency/type/state before and after, and verify audit history
and reports before live rollout. Ambiguous variants must remain separate unless approved.
This PR does not perform those merges or claim that canonicalization is complete.

## DATA-02: Additive exact-money contract

Financial responses retain their existing numeric fields for compatibility and add
a versioned `money` object. Its decimal strings are generated directly from integer
cents, never reconstructed from legacy floating-point JSON values.

```json
{
  "amount": 12.34,
  "currency": "USD",
  "money": {
    "version": "decimal-v1",
    "currency": "USD",
    "values": { "amount": "12.34" }
  }
}
```

The same contract covers transactions, accounts (including negative balances),
transfers, recurring schedules, budgets, dashboard totals and chart points, monthly
reports, category totals/trend arrays, reconciliation and transaction audit snapshots.
For each object, `values` uses its monetary field names, such as `balance`, `income`,
`spent`, or `totals`. Existing `*_cents` fields use names without the suffix inside
`values`. Missing legacy audit currency is not guessed: its `money` value is null.
Percentages and counts remain ordinary numbers and are not monetary values.

Strings use an optional minus sign, digits, and exactly two decimal places, with no
exponent or grouping separators. This preserves amounts above JavaScript's safe-integer
range as well as negative values. Python clients should use `Decimal`; JavaScript
clients can use `decimalToCents` / `centsToDecimal` from
`frontend/utils/exact-money.js` for BigInt arithmetic. Do not convert exact values to
`Number` or calculate with the legacy numeric fields.

Browser CSV export now prefers exact amounts and retains trailing cents. Existing
display/chart clients continue using the legacy fields during the compatibility
period. Money input endpoints already accept decimal strings; clients should submit
those rather than approximate numbers. Legacy fields are not deprecated or removed
until all consumers have migrated. Any future breaking money representation must
use a new contract version. No stored-money or schema migration is required.
