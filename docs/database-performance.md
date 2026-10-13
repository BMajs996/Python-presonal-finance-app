# Database query and capacity improvements

## Deployment

Back up the database before upgrading and stop old application processes. Install
`backend/requirements.txt`, then start the new release. SQLite migration 7 and
PostgreSQL migration 2 add six indexes without changing financial rows or amounts.
Index creation is transactional, not concurrent: PostgreSQL takes the existing
writer reservation and uses the startup lock/statement timeouts. A large database
may need a separately planned maintenance window. A failed index upgrade rolls
back its indexes and version marker and can be retried.

PostgreSQL now upgrades its existing version-1 schema instead of requiring an empty
database. Unknown/future or incomplete migration histories are rejected on both
engines. SQLite's older migrations retain their historical implementation; this
change does not rewrite the desktop-era migration chain.

Do not manually lower a version marker to roll back. Older releases may reject the
new version. Use a tested pre-upgrade backup and a coordinated application rollback.

## CSV query budgets

CSV remains limited to 1,000 rows. Active account IDs/currencies are fetched in
groups of at most 100. Duplicate identities are joined through a parameterized
VALUES table, also in groups of 100 (700 parameters per query).

A 1,000-row preview with one account and distinct identities now uses 11 SQL
executions, or 12 with the default-account lookup. Previously these cases used
2,000 and 3,000 executions. Repeated identities reduce the lookup count further.
Account validation and duplicate lookups stay inside the same writer transaction
for commits. Preview is advisory; commit always rechecks current data.

Writes still insert each valid financial row and preserve database audit triggers,
exact cents, rollback, same-batch duplicate detection and durable retry receipts.
The description comparison remains the backend's existing lower(trim(...))
comparison, rather than silently changing Unicode/category identity policy.

## Indexes and queries

- Live transaction indexes cover date/ID ordering, globally and per account.
- Live expense/category/date supports month-to-date budget joins.
- Transfer account/date indexes support posted account balances.
- Active recurring next-date/ID supports due selection and oldest-due monitoring.

Budget filters use a direct date range, not a month substring. Account queries
compute transaction net/count together, filtering to the selected accounts before
aggregation. Hidden inactive accounts are not included in the active-list aggregate;
single-account lookups constrain it to the requested account. Transfer totals retain
indexed subqueries. Tests count aggregate inputs on SQLite and inspect actual
grouped rows in PostgreSQL EXPLAIN output, without timing-based CI assertions.
Recurring passes select at most 100 schedules and create at most 100 occurrences
per schedule. Large backlogs require additional passes; they are not discarded.

On one isolated local PostgreSQL test with 50,000 synthetic rows, the unfiltered
100-row live transaction page changed from a sequential scan/top-N sort (~17 ms)
to an indexed read (~0.09 ms). These are illustrative query timings, not API or
production latency guarantees. Exact COUNT queries, deep OFFSET pagination,
substring search and full-history balance aggregates remain possible costs.
Existing indexes are retained for compatibility; review redundancy after measuring
real workloads. New indexes also consume disk and increase write work.

## Bounded PostgreSQL pool

The application uses the official [Psycopg connection pool](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).
Defaults, per application process:

| Setting | Default | Meaning |
| --- | --- | --- |
| DATABASE_POOL_SIZE | 5 | Maximum pooled physical connections |
| DATABASE_POOL_TIMEOUT | 2 | Seconds to wait for a pooled connection |
| DATABASE_POOL_MAX_WAITING | 20 | Maximum queued acquisition requests |

Pool exhaustion produces a sanitized HTTP 503 with Retry-After: 2, including
authentication middleware checks. Existing login/hash/body limits remain in force;
the pool is not an HTTP rate limiter. Do not multiply workers without budgeting
their combined connection/queue limits against PostgreSQL capacity.

Connections are returned through a finally block. Uncommitted work rolls back.
Before reuse, DISCARD ALL removes temporary objects, session locks and settings;
normal query timeouts and row handling are restored. Server-side prepare is
disabled to avoid a stale prepared-statement cache after DISCARD. Startup URL
settings, including isolated test-schema search_path, are preserved. Reset happens
in a pool worker; immediately after saturation a caller may still receive 503
while cleanup completes. A checkout check detects disconnected backends; broken
connections are discarded and replaced by the pool.

The readiness probe deliberately retains its separate, bounded read-only
connection. Startup/maintenance compatibility connections are outside the pool;
the HTTP application closes its bootstrap connection and closes the pool during
shutdown. Budget these additional connections and administrative tools separately.
Do not cache authentication/session decisions or share connections between requests.

The global financial writer lock is unchanged. Pooling does not make financial
writes parallel; safe per-user locking belongs to a later isolation change.

## Verification

Query-budget, maximum-import, rollback, index-upgrade failure/retry, connection
reuse/reset, capacity rejection and schedule-batch tests run against both engines
where applicable. Timing thresholds are intentionally not CI assertions. Use
EXPLAIN (ANALYZE, BUFFERS) on representative read queries before adding more indexes
or changing lock granularity. Production data was not modified to benchmark this
release.

Regression tests also cover simultaneous identical rows under different CSV batch
IDs, account deactivation after preview, real constraint failure during import,
startup cleanup after authentication initialization fails, and very large or
incomplete migration histories. Queue tests distinguish TooManyRequests from
PoolTimeout and verify that an already queued caller is served after release.
