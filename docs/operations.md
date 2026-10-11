# OPS-01 / OPS-02: operational health

This release keeps financial processing and the existing `/api/health` response
compatible. No database migration is required. Worker diagnostics live in memory
and reset at process startup. The supported deployment has one Uvicorn process;
do not use these records as shared metrics across multiple workers/hosts.

## Endpoints

| Endpoint | Access | Meaning |
| --- | --- | --- |
| GET /api/health | Public | Process liveness only; 200 with status=ok |
| GET /api/health/ready | Public | Database and expected schema ready; 200 or generic 503 |
| GET /api/health/worker | Public | Minimal worker status; 200 ok/starting or generic 503 |
| GET /api/operations/health | Owner session | Database readiness and detailed worker state |

All responses use Cache-Control: no-store. Production HTTPS, exact host allowlists
and proxy trust still apply. Only the three exact public health paths bypass owner
authentication. Private diagnostics depend on database-backed session validation;
use the public probes when the database is down. Readiness deliberately stays
healthy during a recurring-only failure when the database/schema are healthy.

Private diagnostics include UTC event timestamps, monotonic duration, last created
count, failure count/classification, captured business date, oldest remaining due
date and lag days. During a failed pass, created count and lag are null: earlier
schedules may already have committed, so zero would be misleading. No financial
amounts, descriptions, account IDs, credentials or driver exception messages are
included. A historical last-error code remains available after recovery; current
status is determined by current failure count and health reasons.

## Capacity and time limits

Readiness permits one probe at a time per process and caches success AND failure
for five seconds. Concurrent uncached requests fail closed with 503 rather than
queueing database connections. Public worker checks read memory only; liveness
does no database work. This bounds readiness-driven DB work to at most one probe
per five seconds per process. It is not a general HTTP/DDoS rate limiter.

PostgreSQL probes use a dedicated read-only connection, a two-second connection
timeout and two-second statement/lock timeouts set at connection startup. Existing
URL options such as test schema search_path are preserved. Connection timeouts
apply per connection target, not an absolute end-to-end DNS/multi-host deadline.
SQLite probes open the existing database read-only, with a two-second lock wait
and a monotonic progress deadline. They never create a DB or run migrations.
Probes validate the expected schema version, base currency and required columns.

Do not poll more often than once a minute. Readiness 503 includes Retry-After: 5;
worker 503 includes Retry-After: 60. Public responses expose only generic status.
Keep the app port private and the existing reverse-proxy admission controls.

## Worker policy

| Setting | Default |
| --- | --- |
| RECURRING_INTERVAL_SECONDS | 60 |
| RECURRING_MAX_BACKOFF_SECONDS | 300 |
| RECURRING_STALE_SECONDS | 180 |
| RECURRING_FAILURE_THRESHOLD | 3 |
| RECURRING_LAG_DAYS | 1 |

Failed passes retry after 60, 120, 240, then at most 300 seconds by default.
Success resets the consecutive-failure count and normal interval. A separate
five-second observer notices stalls even while DB work runs in a thread. Staleness
is measured from the processing start, or the next expected attempt plus the stale
allowance, so normal backoff does not generate a false heartbeat alarm.

Startup returns worker status=starting for at most the stale allowance without
progress. A stopped task, stalled processing, repeated failures or backlog lag
produces transition-based ERROR alerts; recovery produces an INFO event. Attempt
warnings contain only a controlled classification, frame function/line locations
and retry delay. No raw traceback/source/locals, SQL values or exception text are
logged. An initial one-off failure is still visible as a degraded public worker
probe, even before the repeated-failure alert threshold is reached.

Due dates use one business-date snapshot per processing pass. Backlog can remain
after a successful bounded batch; lag reports remaining active schedules, not only
whether the last call raised. A schedule due today has lag=0; the default lag alert
starts at one overdue business-calendar day. Check for a backlog before lowering
the lag threshold or changing processing intervals.

On shutdown, the observer signals a thread-safe stop flag. Processing stops at
occurrence/schedule boundaries, retaining completed claims and the next due date.
It does not cancel an active database statement or duplicate committed entries.
Existing database timeouts and systemd's stop timeout still apply; forced termination
may roll back the current schedule. Stalled work is reported, never started again
concurrently to try to bypass a blocked thread.

## Monitoring and alerts

Run the credential-free monitor after starting the app:

```bash
.venv/bin/python -m backend.app.operations_check --url http://127.0.0.1:8000
# Production requires the real HTTPS origin, not direct plaintext Uvicorn access:
.venv/bin/python -m backend.app.operations_check --url https://centspan.online
```

The command checks three probes sequentially with five-second request timeouts,
bounded response reads and exit code 1 on unavailable, invalid or redirected
responses. It logs only probe names and generic statuses. Startup status is accepted
only while the server's finite startup grace applies.

Optional deployment: copy finance-operations-check.service and its timer into
/etc/systemd/system after replacing the example HTTPS origin in ExecStart. Run
systemctl daemon-reload, test the service once, then enable --now the timer. It runs
one check per minute after completion; systemd does not overlap an active oneshot.
Inspect journalctl -u finance-dashboard and -u finance-operations-check.service.

Local journal alerts and monitor exit status are implemented. Email/phone delivery
is NOT configured automatically: wire a reviewed OnFailure notification service
or an external HTTPS monitor to a chosen delivery channel. A restart must not be
used as a substitute for diagnosis of persistent schedule errors. Production
installation, external notification delivery and verification remain deployment
tasks; local tests do not establish those live operational controls.

## Verification

Test failures and recovery in disposable databases, never by stopping production
PostgreSQL or corrupting real schedules. Tests cover rate protection, schema/currency
failures, public/private access, failure backoff, stale processing, backlog,
business-midnight boundaries, sanitization and cooperative shutdown/idempotency.
Before deploying: CI, reviewed PR, fresh verified backup, then restart and check
all probes. Confirm private diagnostics after owner login and monitor a successful
recurring pass. No production services are changed by this documentation.
