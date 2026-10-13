import http from "k6/http";
import { check } from "k6";
import execution from "k6/execution";
import { Counter, Rate, Trend } from "k6/metrics";

const base = __ENV.BENCH_BASE;
const rate = Number(__ENV.BENCH_RATE);
const seconds = Number(__ENV.BENCH_SECONDS);
if (!/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(base || "") ||
    !Number.isInteger(rate) || rate < 1 || rate > 20 ||
    !Number.isInteger(seconds) || seconds < 5 || seconds > 30 || !__ENV.BENCH_COOKIE) {
  throw new Error("Only a bounded, locally generated benchmark target is allowed");
}

const unexpected = new Rate("unexpected_responses");
const capacity = new Counter("capacity_rejections");
const limited = new Counter("rate_limited");
const transport = new Counter("transport_errors");
const reads = new Counter("read_requests");
const latency = new Trend("read_latency", true);
const paths = ["/api/dashboard?days=30", "/api/accounts", "/api/transactions?limit=100",
  "/api/transactions?type=expense&account_id=1&limit=100", "/api/reports/monthly?months=12"];

export const options = {
  scenarios: { reads: { executor: "constant-arrival-rate", rate, timeUnit: "1s",
    duration: `${seconds}s`, preAllocatedVUs: 10, maxVUs: 50, gracefulStop: "15s" } },
  thresholds: { unexpected_responses: ["rate<0.01"], dropped_iterations: ["count==0"] },
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};

export function setup() {
  const response = http.get(base + "/api/benchmark/pool", {
    headers: { Cookie: __ENV.BENCH_COOKIE }, timeout: "10s", redirects: 0,
  });
  if (response.status !== 200 || response.json("pool_size") === undefined) {
    throw new Error("Target is not the isolated benchmark server");
  }
}

export default function () {
  const path = paths[execution.scenario.iterationInTest % paths.length];
  const response = http.get(base + path, { headers: { Cookie: __ENV.BENCH_COOKIE },
    timeout: "10s", redirects: 0, tags: { name: path } });
  check(response, { "read succeeds": (r) => r.status === 200 });
  reads.add(1);
  latency.add(response.timings.duration);
  unexpected.add(response.status !== 200);
  capacity.add(response.status === 503 ? 1 : 0);
  limited.add(response.status === 429 ? 1 : 0);
  transport.add(response.status === 0 ? 1 : 0);
}

export function handleSummary(data) {
  const count = (name) => data.metrics[name]?.values?.count || 0;
  return { [__ENV.BENCH_PHASE_REPORT]: JSON.stringify({
    requested_rps: rate, duration_seconds: seconds, requests: count("read_requests"),
    achieved_rps: data.metrics.read_requests?.values?.rate || 0,
    latency_ms: data.metrics.read_latency?.values || {},
    unexpected_rate: data.metrics.unexpected_responses?.values?.rate || 0,
    capacity_503: count("capacity_rejections"), limited_429: count("rate_limited"),
    transport_errors: count("transport_errors"), dropped_iterations: count("dropped_iterations"),
  }, null, 2) };
}
