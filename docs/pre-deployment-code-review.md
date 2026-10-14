# Pre-deployment code and database review

Reviewed: 2026-10-13. Scope: independent user accounts, finance repositories,
authentication storage, connection management, integration tests, and browser workflows.

## Changes

### Targeted budget reads

Creating or updating one budget previously recalculated usage for every budget
belonging to the user. Writes now use `RETURNING id` and read only that budget.
Updating an unknown or another user's budget still returns no result.

The expense query binds the authenticated owner directly in its account subquery,
instead of correlating that lookup with each budget. Month, posted-date, category,
soft-deletion, and ownership rules are unchanged.

Regression tests verify two SQL calls for a successful budget write, one for a
missing update, and retained budget identity during an upsert. A SQLite aggregate
probe with 12 budgets and 20 expenses per budget records 20 input rows when saving
one budget, instead of the 240 rows required to recalculate every budget. This is
a query-work measurement, not a claim of a twelvefold production latency gain.

### Indexed authentication cleanup

Add idempotent indexes for `window_start` on the source and target rate-limit
tables, and for `expires_at` and `last_seen` on sessions. These support expiration
cleanup before authentication without changing limits or session lifetime.

Tests seed 2,000 records per table, refresh optimizer statistics, and verify that
SQLite and PostgreSQL execution plans select the appropriate cleanup indexes.
Repeated authentication initialization must preserve valid sessions.

These operational indexes are installed during authentication initialization;
this change does not add another versioned financial schema migration.

### Connection cleanup

Close newly opened SQLite and PostgreSQL connections if initial configuration
fails, then propagate the original exception. PostgreSQL direct and pooled
connections reuse the same timeout configuration. Failure-injection tests cover
both paths without contacting production.

A separate resource-cleanup probe located an unclosed SQLite connection in the
existing PostgreSQL migration writer-lock test. Its transaction context is now
combined with explicit connection closure; a transaction context alone does not
close a SQLite connection.

### Profile and session separation

Separate session rendering and refresh from profile loading. Revoking another
session no longer reloads profile fields or discards an unsaved profile draft.
Full profile loading remains appropriate on navigation and after a successful save.

Browser regressions exercise another device's independent cookie jar, individual
revocation, revoking other sessions, and revoking the current session. A simulated
429 profile save verifies retained input, an enabled retry button, and a subsequent
successful save persisted across reload.

## Database assessment

The local development database was inspected through a read-only connection.
It is PostgreSQL, with approximately 9 MB of storage and only a few financial
records. This is not a representative production performance workload.

Existing tests already bound CSV account/duplicate reads for 1,000-row imports,
verify account aggregation excludes unselected history, exercise PostgreSQL query
plans with 10,000 transactions, and cover bounded recurring selection. Account,
transfer, ledger-date, due-schedule, and ownership indexes remain in place.

No additional financial indexes, caches, denormalized owner columns, or pagination
contract changes were added without a demonstrated need.

## Validation

The backend suite includes SQLite and PostgreSQL repository/API integration,
migrations, rollback, financial invariants, concurrency, ownership, authentication,
and real local TLS-proxy tests. PostgreSQL tests use disposable schemas in a
database whose name must end in `_test`.

Run the complete verification with:

```bash
TZ=UTC TEST_DATABASE_URL=postgresql:///finance_dashboard_test REQUIRE_PROXY_TESTS=1 \
  .venv/bin/pytest --cov=backend/app --cov-branch --cov-report=term-missing
npm test
npm run test:e2e
E2E_DATABASE_URL=postgresql:///finance_dashboard_test npm run test:e2e
.venv/bin/ruff check backend/app backend/tests tests/e2e/server.py
.venv/bin/ruff format --check backend/app backend/tests tests/e2e/server.py
.venv/bin/mypy backend/app
.venv/bin/bandit -q -r backend/app -ll -ii
```

Browser fixtures use disposable databases and enforce CSP checks. Their privileged
invitation/recovery helpers exist only in the test server, not the production app.

The complete SQLite and PostgreSQL browser suites each passed 56 desktop/mobile
tests. All 16 frontend unit tests passed, along with Ruff, formatting, mypy, and
the configured Bandit checks. All 733 backend tests passed, including the
new query, initialization, connection failure, and budget-response regressions.
Coverage is 95.83%, with branch measurement enabled. A temporary full-suite
garbage-collection guard also passed without unclosed SQLite connections. The remaining
Starlette TestClient deprecation warning is a dependency compatibility follow-up,
not suppressed by this change.

## Remaining boundaries

- PostgreSQL financial writes still share a global advisory writer reservation.
  This favors financial correctness but limits concurrent write throughput; do not
  remove it without redesigning and testing cross-record locking.
- Dashboard and historical reports necessarily aggregate ledger history. Measure
  representative multi-user data before introducing caching or summary tables.
- Search with leading wildcards and deep offset pagination may become expensive
  on large ledgers; workload measurements should guide any contract changes.
- Isolation is implemented in application queries and database ownership guards,
  not PostgreSQL row-level security. Database access remains privileged.
- This review is not a production load test, penetration test, or proof that all
  defects have been eliminated. Production backup, deployment, and post-deployment
  smoke checks remain separate steps.

Production and unrelated local edits were not changed.
