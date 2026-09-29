# SEC-01: Single-host deployment contract

**Status: reference configuration and local integration tests, not a verified live deployment.**
No public domain/provider has been chosen. Do not mark SEC-01 fully closed until the
external acceptance evidence below is recorded for the actual host.

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
