# SEC-01: Single-host deployment contract

**Status: deployed at https://centspan.online on DigitalOcean; final acceptance is tracked
in [security acceptance](security-acceptance.md).** Do not mark SEC-01 fully closed
until the external acceptance evidence below is recorded for the actual host.

## Supported topology

Internet -> Nginx HTTPS -> 127.0.0.1:8000 Uvicorn -> PostgreSQL Unix socket/private interface.

This template assumes ONE proxy, on the same host, with no CDN/load balancer.
It does not trust an entire container network or a provider's forwarding headers.
Adding another hop requires a fresh documented trust review; do not add a wildcard
or copy arbitrary client-supplied X-Forwarded-For chains.

The loopback proxy address is a trust boundary for all local processes. Use a
dedicated host with restricted shell access. If untrusted local workloads must
coexist, use a permission-restricted Unix socket and revise/test the launcher and
proxy configuration together instead of assuming loopback identifies Nginx.

## Application preparation

1. Install the release and virtualenv under /opt/finance-dashboard. Use a dedicated
   non-root finance service user. Keep application code and its virtualenv read-only
   to that user; /var/lib/finance-dashboard is the writable state directory.
2. Provision a dedicated PostgreSQL role/database. Prefer a local Unix socket and
   peer authentication for the finance service identity. If using TCP, restrict
   listen_addresses, pg_hba.conf and both host/provider firewalls. Do not publish 5432.
3. Create /etc/finance-dashboard/production.env from production.env.example. Keep
   it outside Git, owned by root with mode 0600 for systemd to read. Configure the
   owner hash locally with the existing setup tool; never put plaintext credentials
   in shell arguments, logs, tickets or this repository. Do not run the interactive
   setup tool as the restricted service account or in the read-only install tree.
4. Set ENVIRONMENT=production, one exact HTTPS CORS_ORIGINS, matching ALLOWED_HOSTS,
   TRUSTED_PROXY_IPS=127.0.0.1, APP_PORT=8000 and BUSINESS_TIMEZONE=Europe/Belgrade.
   ALLOWED_HOSTS contains hostnames, not URLs/ports. No wildcard or proxy CIDR is
   accepted. Use ASCII/punycode domain names. Set the same business settings for
   web and maintenance processes.
5. Install finance-dashboard.service after reviewing its paths. It starts
   python -m backend.app.serve with reload off, one worker, explicit Uvicorn
   forwarded-header trust and a loopback listener. run.py rejects production mode.
   The launcher intentionally disables access logs to avoid recording query data.
   An alternate uvicorn command can bypass launcher protections: do not use one.
6. Run migrations against a verified backup/restored staging copy before pointing
   the service at real data. Keep rollback release/configuration and a tested backup.

## Reverse proxy preparation

Install Nginx with TLS 1.2/1.3 support and configure certificate issuance/renewal.
Use a certificate matching the real hostname. The template requires a valid
certificate BEFORE enabling its HTTPS server; configure ACME bootstrap separately
(DNS validation is one option). It does not provide a port-80 ACME challenge route.

Render nginx.conf.template into a site file included INSIDE Nginx's http block:
- DOMAIN: the exact hostname, e.g. finance.example.com.
- PUBLIC_AUTHORITY: the same hostname (include a port only for nonstandard HTTPS).
- HTTP_LISTEN: 80 for production; HTTPS_LISTEN: 443 for production.
- APP_PORT: the same application port as production.env.
- CERTIFICATE and CERTIFICATE_KEY: reviewed absolute certificate/key paths.
All placeholders must be replaced. For IPv6 service, add corresponding [::]:80
and [::]:443 listeners to EVERY relevant server block and apply matching firewall
rules; test IPv6 externally. Do not publish an AAAA record for an unverified path.
Remove conflicting/default sites for the selected listeners and run nginx -t before
reloading. Keep administrative access open while changing network/firewall rules.

The template rejects unknown hosts, redirects GET/HEAD HTTP navigation to a fixed
HTTPS authority, and rejects plaintext write requests without proxying them.
Redirects cannot undo credentials already sent over plaintext. Never test HTTP
login with real credentials. Clients must begin login over HTTPS.

Nginx overwrites X-Forwarded-For with its transport peer and X-Forwarded-Proto with
its own scheme. It clears alternate forwarding headers, sets a fixed upstream Host,
disables proxy caching, and does not log request bodies/cookies/tokens.
Do not enable a global real_ip_header/set_real_ip_from rule that changes $remote_addr
without reviewing the full upstream trust chain. Never log passwords, cookies,
CSRF tokens, Authorization headers, or request bodies.

## Content Security Policy

The app sends one enforced Content-Security-Policy header on the UI and assets.
The policy allows same-origin external scripts and styles, and blocks inline scripts,
event handlers and style attributes. object-src, base-uri, and frame-ancestors are
set to 'none'; X-Frame-Options: DENY remains as a compatibility header.
Nginx should forward this header unchanged. Do not add another CSP or a
Report-Only header at the proxy: multiple enforced policies apply together and may
block valid pages. The real-proxy test checks for one policy header.

Before launch, use a staging HTTPS origin to exercise login, charts, modals, CSV
import, budgets and sign-out. Review securitypolicyviolation events and the
browser console. Compare the delivered header with the app policy, and test that
synthetic inline scripts and event handlers do not run. If a legitimate workflow
is blocked, restore the prior release while fixing the violation, then repeat the
staging checks. No public staging origin has been verified by these local tests.

## HSTS rollout

HSTS is OFF in the template. First verify external HTTPS, the full certificate chain,
renewal and recovery. Then enable the commented max-age=300 header on HTTPS responses,
verify it, and increase the lifetime deliberately. Do not add includeSubDomains or
preload until every affected domain has been reviewed. A cached HSTS policy cannot
be instantly undone for clients that cannot connect over HTTPS.

## Test layers

Unit tests validate settings, production launcher options, Host rejection and the
installed Uvicorn middleware's exact-peer trust behavior.

The real-proxy tests start the same Nginx template and production launcher on ephemeral
loopback ports, with a locally trusted test certificate, synthetic credentials and
disposable SQLite/PostgreSQL data. Nginx is NOT installed or started as a system service
by the tests. Run:
```bash
NGINX_BINARY=/path/to/nginx REQUIRE_PROXY_TESTS=1 \
TEST_DATABASE_URL=postgresql:///finance_dashboard_test \
.venv/bin/pytest backend/tests/test_proxy_boundary.py backend/tests/test_real_proxy.py -q
```
Without Nginx, real-proxy tests skip locally; REQUIRE_PROXY_TESTS=1 makes that a failure.
CI requires them. The tests validate certificate trust rather than using verify=False.
Two loopback source addresses test independent throttling without spoofed header IPs.
This proves local routing behavior, NOT internet-facing port isolation or real DNS/TLS.

## External acceptance: required before launch

Record the deployed commit, rendered configuration, effective launch command,
actual trusted proxy peers and verification date. Never record secrets.

- From an external machine, HTTP GET redirects to the exact HTTPS origin with no
  attacker-controlled hostname. A synthetic HTTP login POST is rejected and does
  not reach application authentication.
- HTTPS has a valid hostname/chain and renewal is tested. UI/assets/API share one origin.
- HTTPS login succeeds; cookies have Secure, HttpOnly, SameSite=Strict and Path=/.
  Session reads, CSRF-protected writes and logout work; wrong Origin/CSRF are rejected.
- Spoofed/repeated X-Forwarded-For, X-Forwarded-Proto, Forwarded and alternate IP/host
  headers cannot change the application's client identity or downgrade/bypass HTTPS.
  Inspect sanitized local evidence or throttling counters, never expose a public
  diagnostic endpoint.
- Two genuinely different external public IPs are tested: source A reaches its
  ten-attempt limit, source B can still log in. Stay below the intentional global
  100-attempt/minute limit and hashing capacity limit. The limiter counts attempts,
  not only failures. Clients behind one NAT still share one IP-based limit.
- Scan the actual app and DB ports from outside over every published IPv4/IPv6 path:
  they must be unreachable. Confirm no container publishing, cloud rule or secondary
  interface bypasses this. Local binding inspection alone is insufficient.
- Unknown Host/SNI names are rejected, including requests addressed directly to
  the public server IP. A CDN/load balancer requires separate origin-bypass tests.
- HSTS is enabled only after these checks; verify its header and chosen rollout lifetime.

Rollback to the prior known-good release/configuration if checks fail. Do not work
around failures by trusting every proxy, disabling production HTTPS/CSRF enforcement,
or exposing the database. Maintain certificate/renewal monitoring and alerting for
unexpected login throttling after launch.

References:
- https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header
- https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_reject_handshake
- https://starlette.dev/middleware/#trustedhostmiddleware
- https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html

## SEC-02: Request admission before application work

The reference proxy buffers each complete request before forwarding it to Uvicorn.
It enforces these serialized body-byte limits, regardless of Content-Length or
HTTP/1.1 chunked framing:

| Route | Body limit | Idle body-read timeout |
| --- | --- | --- |
| /api/auth/login (including trailing slash) | 16 KiB | 5 seconds |
| /api/transactions/import | 8 MiB | 15 seconds |
| /api/transactions/import/preview | 8 MiB | 15 seconds |
| Other proxied requests | 2 MiB | 10 seconds |

CSV trailing-slash variants have the same limit. Query strings do not change route
selection. Tests include an encoded login path to guard against limit bypass.
A 10-second header-read timeout is configured at the http level; avoid duplicating
that directive in the surrounding nginx.conf when including this template.

Oversized requests receive HTTP 413 before the application parses JSON, verifies a
password, validates a session, or writes financial data. Incomplete uploads are
closed on timeout; Nginx may record 408 without sending a response body. Clients
must handle both a timeout/connection closure and an HTTP error.

### Why these byte limits

Login permits 100 username characters and 1,024 password characters. JSON can encode
one non-BMP Unicode character as two escaped surrogate values, consuming 12 bytes.
The resulting maximum-length field fixture is below 16 KiB, including JSON syntax.

CSV requests permit 1,000 rows, with 100 category characters and 500 description
characters per row. The escaped text alone can occupy 7,200,000 bytes:
1,000 * (100 + 500) * 12. JSON field names, dates, amounts, account references and
the batch UUID need additional space. An 8 MiB limit accommodates the tested
maximum-length Unicode fixture; a 2 MiB blanket limit did not.

The integration fixture uses 1,000 distinct rows with all category/description
characters occupying 12 escaped bytes. It tests chunked preview, ordinary import,
and an equivalent UTF-8 retry, confirming exactly 1,000 inserts rather than 2,000.
This is a bounded wire contract, not a guarantee that arbitrary whitespace,
unbounded numeric spellings, unknown properties, or repeated JSON keys fit.
Clients should use ordinary compact JSON and respect the independent row limit.

### Memory, disk, and slow-client limits

proxy_request_buffering is explicitly enabled, including for chunked requests.
client_body_buffer_size is 16 KiB; larger bodies can spill to Nginx's private
temporary directory instead of being held entirely in application memory.
The limit bounds admitted body bytes, not the entire Python object's memory after
a valid request is parsed. Concurrent valid imports can still consume resources.

Keep the Nginx body temporary directory private to the service, monitor available
space, and size/restrict its filesystem for the expected concurrency. Do not enable
persistent request-body files or body logging. Review worker/connection capacity,
per-source/global concurrency limits and upstream capacity on the actual host.
The tests include a coarse Linux resident-memory regression check after repeated
rejections, not a peak-memory or concurrent-load capacity certification.

Important: client_body_timeout limits the gap between reads, NOT total upload
duration or a minimum transfer rate. A client sending occasional bytes before
the timeout can hold a connection longer. This configuration is not a complete
slow-drip or DDoS defense. A total upload deadline/minimum rate requires an
appropriate additional edge capability and separate tests; do not claim the
5/15-second values enforce total request deadlines.

### Why there is no ASGI byte limiter here

The supported public path is Nginx -> private loopback Uvicorn. Keeping rejection
before any application work avoids a second full-body buffer and stream/response
ordering complexity inside ASGI. Development's direct Uvicorn launcher does NOT
provide these edge limits and must not be exposed publicly.

If a later topology permits direct application access or requires defense in
depth, implement and independently test a bounded ASGI receive wrapper. It must
count streamed chunks and reject cleanly before starting a response; raising from
a late receive callback alone is insufficient. Do not assume Content-Length is
present or honest.

### Regression and launch checks

Run the real-proxy tests described above. They cover both SQLite and PostgreSQL:

- Known-length and chunked oversized login, import, and preview requests.
- Unauthenticated and authenticated import rejection before upstream access.
- Login byte-boundary acceptance and maximum-length escaped login fields.
- Incomplete login/import uploads ending at their route-specific idle timeout.
- Query, trailing-slash, encoded-path and default-route limit behavior.
- No login counter changes, password work, or transaction inserts for rejected
  requests; a test-only status/upstream log confirms no Uvicorn connection.
- A maximum-length 1,000-row Unicode preview/import and idempotent UTF-8 retry.
- Existing SEC-01 HTTPS, forwarding, CSRF, cookie and login-isolation behavior.

Before launch, repeat the byte-limit and incomplete-upload checks through the real
public endpoint using synthetic credentials/data. Verify that no CDN, alternative
location, inherited buffering directive, public app port, or alternate listener
bypasses these controls. Measure concurrent upload memory/temp-disk use on staging.
No public deployment or external load verification has been performed by this PR.

References:
- [Nginx request body limits and buffers](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
- [Nginx body-read timeout semantics](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_body_timeout)
- [Nginx proxy request buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering)
