# Local performance baseline

Install the development requirements and [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/), then run:

```bash
BENCH_DATABASE_URL=postgresql:///finance_dashboard_test .venv/bin/python -m benchmarks.run
```

The database must already exist, be local, and have a name ending in `_test`.
The benchmark creates its own UUID schema and removes it after stopping its server,
including normal failure/interrupt paths. It never accepts an HTTP target argument.
Do not run other tests against the same test database concurrently: financial advisory
locks are database-wide. The development app on port 8000 is not used.

Defaults: 100,000 deterministic synthetic transactions across 100 accounts (10
active), 1,000 transfers, five budgets, USD, Europe/Belgrade, one Uvicorn process,
no reload, and the normal five-connection pool. The normal auth, CSRF and request
body controls remain enabled. A generated owner password and one shared synthetic
session are passed only through child environment variables, not saved in reports.
The server uses an ephemeral loopback port and is always terminated on completion.
Its diagnostic pool route exists only in the benchmark process, requires auth,
and is not installed in the production application.

Serial profiling warms each operation once, then takes five samples: dashboard,
accounts, transaction pages, account/type filtering, monthly reports, and a 1,000-row
CSV preview. These measure complete HTTP operations including response parsing;
five samples are descriptive, not statistically reliable tail percentiles.

k6 then performs four read-only phases at 1, 5, 10 and 20 iterations/second, with
one GET per iteration, 15 seconds per phase, and at most 50 virtual users. The
server marker is checked before each phase to reject ordinary development targets.
Latency and request counts exclude that setup request. Login is done once outside
the load phases; login brute-force testing is deliberately not part of this tool.

```bash
# Short smoke test, smaller disposable dataset:
.venv/bin/python -m benchmarks.run --rows 1000 --seconds 5

# Use a locally extracted k6 binary without installing system packages:
.venv/bin/python -m benchmarks.run --k6 /path/to/k6
```

Bounds are enforced: 1..100,000 rows, 5..30 seconds per phase, max 20 iterations/s.
This is a controlled baseline, not a large stress/soak or production capacity test.
The [arrival-rate executor](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/)
starts iterations at the requested rate independently of response speed. Record
dropped iterations as well as achieved throughput; low throughput may be a load
generator limitation, not exclusively a server problem.

Results are in the ignored `benchmark-results/<timestamp>/summary.json` and per-rate
JSON files. They include latency p50 (`med`), p95/p99/max, achieved throughput, 503,
429, transport errors, dropped iterations, cumulative pool stats, sampled process
RSS, and CPU lifetime average. CPU samples include startup/seeding; RSS samples are
not a peak-memory guarantee. They do not measure PostgreSQL resource usage, proxy
latency or TLS. The client and server share the laptop's resources.

Below 1% unexpected responses and zero dropped iterations are baseline thresholds,
not a product SLA. Threshold failures keep the report and produce exit code 1.
There is no assumed latency SLA before collecting a baseline. Counts and row-state
fingerprints of financial tables must match before/after; auth session activity can
legitimately update. A 503 at saturation is capacity protection, but counts as a
failed read in this baseline. The tool does not disable limits or retry away errors.

Compare repeated runs on identical hardware/configuration and data sizes. Do not
translate request rates into a supported user count: this test uses one owner/session
and does not test independent-user isolation. A later staging run through Nginx/TLS,
with a separate load generator, is needed before making droplet capacity claims.
