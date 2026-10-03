# SEC-01 and SEC-04 acceptance

## SEC-01: verified single-proxy deployment

Status: deployment boundary verified on 2026-10-03 for the current published
IPv4 origin and single-host Nginx topology. Revalidate after network, proxy,
DNS, launcher or authentication changes.

Reviewed 2026-10-03: DigitalOcean 209.38.252.91, centspan.online, deployed commit
7d0dd51. The service is active under the non-root finance user and launches
`python -m backend.app.serve`. Socket inspection shows Uvicorn on 127.0.0.1:8000,
PostgreSQL on 127.0.0.1:5432 and [::1]:5432, and Nginx on IPv4 ports 80/443.
The enabled Nginx site overwrites forwarded scheme/client headers, clears alternate
headers, fixes upstream Host, rejects unknown hosts, and rejects HTTP writes.
HSTS was initially commented out and was subsequently enabled by the owner.

External checks from the laptop on 2026-10-03 passed: trusted HTTPS login page,
HTTP redirect, HTTP write rejection, one enforced CSP, frame denial, unknown-Host
rejection, and blocked public 8000/5432 on the published IPv4 address. The initial
HSTS check failed before it was enabled. No IPv6 address was returned for the hostname.
The owner confirmed on 2026-10-03 that `certbot renew --dry-run` succeeded for
the centspan.online certificate. Isolated proxy tests passed (32 passed; five
PostgreSQL cases skipped because TEST_DATABASE_URL was not configured).
After the owner enabled HSTS, all external script checks passed on 2026-10-03,
including HSTS. The owner confirmed the session cookie attributes Secure, HttpOnly,
SameSite=Strict and Path=/, and confirmed that the laptop was rate-limited while
a login over the phone's mobile connection succeeded on 2026-10-03.
Live spoofed-header checks passed on 2026-10-03: after the laptop source reached
429, three different forged client identities with forwarded/alternate headers
remained at 429 despite claimed HTTP scheme and an untrusted forwarded host.
A plaintext login claiming forwarded HTTPS was rejected with 400. Only synthetic
invalid credentials were used. The owner supplied the selected production settings:
ENVIRONMENT=production, CORS_ORIGINS=https://centspan.online,
ALLOWED_HOSTS=centspan.online, TRUSTED_PROXY_IPS=127.0.0.1 and APP_PORT=8000.
The owner enabled UFW and confirmed Status: active, with inbound rules allowing
only OpenSSH (22) and Nginx Full (80/443), for IPv4 and IPv6. A fresh external SSH
connection succeeded, the finance service remained active, and all public boundary
checks passed again after enabling the firewall. DigitalOcean cloud-firewall
configuration was not independently inspected; isolation is supported by local
bindings, the enabled host firewall and observed external port rejection.

Run from the laptop, with normal internet access:

```bash
python3 deploy/verify-public-boundary.py centspan.online
```

Every result must be true. Inconclusive IPv6 routing requires another external
machine with IPv6 access. Repeat if DNS gains an AAAA record or the topology changes.
This script validates the certificate using system trust and does not log in,
change financial data, or deliberately exhaust production login limits.

On the server, run these locally; never paste passwords or the full environment:

```bash
sudo nginx -t
sudo certbot renew --dry-run
sudo grep -E '^(ENVIRONMENT|CORS_ORIGINS|ALLOWED_HOSTS|TRUSTED_PROXY_IPS|APP_PORT)=' /etc/finance-dashboard/production.env
sudo ufw status verbose
```

Expected settings: production, https://centspan.online, centspan.online,
127.0.0.1 and 8000 respectively. Confirm the effective PostgreSQL configuration
and DigitalOcean firewall rules also exclude public database/app ports.

After certificate renewal and HTTPS checks succeed, enable the existing HTTPS-only
HSTS line (`max-age=300`) in /etc/nginx/sites-available/centspan. Run `sudo nginx -t`
before `sudo systemctl reload nginx`. Repeat the external check. Increase HSTS
lifetime only after observing stable HTTPS; do not add subdomains or preload.

In a browser, log in using credentials entered only there. Verify the session
cookie has Secure, HttpOnly, SameSite=Strict and Path=/ in developer tools.
Verify a CSRF-protected write and sign-out. Record pass/fail, never cookie values.

The isolated tests below cover overwritten/spoofed forwarded headers and independent
transport source limits through the same proxy template, using synthetic accounts:

```bash
REQUIRE_PROXY_TESTS=1 TEST_DATABASE_URL=postgresql:///finance_dashboard_test \
  .venv/bin/pytest backend/tests/test_proxy_boundary.py backend/tests/test_real_proxy.py -q
```

Final live source-isolation acceptance needs two distinct public IPs (for example
laptop broadband and phone mobile data, with Wi-Fi disabled). In a controlled
window, source A reaches the ten-attempt login limit with synthetic wrong passwords;
source B must still log in. Repeating source A with spoofed forwarded headers must
not bypass its limit. Coordinate this to avoid locking out the owner's current
source. Do not send real credentials over HTTP. Record date and result only.

Renewal, HSTS, cookie attributes, two-source login isolation, live header spoofing,
selected production settings and external port checks are recorded above. This
verification covers the current IPv4 single-proxy deployment. Publishing IPv6 or
adding a CDN/load balancer requires fresh external tests and a revised trust review.

## SEC-04: laptop-only encrypted backups

The existing 2026-10-01 archive was encrypted with age and restored successfully
into a disposable local PostgreSQL database. On 2026-10-03 the private identity was
moved to ~/.config/centspan-keys/identity.txt, separate from the archive directory,
and the existing archive was fully decrypted/read successfully using the moved key.
An independent recovery-key copy is still required.
The owner has no separate recovery medium available as of 2026-10-03; this
requirement remains open and SEC-04 is partially complete.

The new finance-20261003T120755Z.dump.age archive was streamed directly to the
laptop and fully decrypted/read by pg_restore without plaintext files. The laptop
user timer was enabled, with the next run at 2026-10-03 19:04 Europe/Belgrade.
After the owner created a disposable local database, the new archive was restored
on 2026-10-03 with pg_restore --exit-on-error. Checks passed for integer-cent money
consistency, net-zero transfers, account/audit/reconciliation links, validated
constraints, account presence and PostgreSQL migration history. The temporary
database was dropped after verification. No independent comparison with the exact
source-snapshot counts/totals was performed; restore checks must not be described
as a full source reconciliation. A manual run through the installed user service
also completed with Result=success and ExecMainStatus=0.

Move the identity on the laptop into a private directory outside the archive path:

```bash
install -d -m 700 "$HOME/.config/centspan-keys"
mv "$HOME/.config/centspan-backups/identity.txt" "$HOME/.config/centspan-keys/identity.txt"
chmod 600 "$HOME/.config/centspan-keys/identity.txt"
```

This separation prevents accidentally copying the key with the archives, but does
not protect against a compromised laptop account. Keep an additional identity copy
on an encrypted removable device stored separately. Losing every copy of the key
makes the backups unrecoverable. Do not upload the identity to Git or the server.

### Enable streaming backups

The laptop script streams pg_dump from PostgreSQL through SSH into age. Only
ciphertext is stored; it writes no server-side archive or plaintext laptop dump.
It decrypts and reads the complete archive before publishing a final filename.
Failed commands leave no completed archive. This is archive verification, not a
substitute for a database restore drill.

The deploy account needs permission for one exact read-only dump command. On the
server use `sudo visudo -f /etc/sudoers.d/centspan-backup` and enter:

```sudoers
deploy ALL=(finance) NOPASSWD: /usr/bin/pg_dump --dbname=finance_dashboard --format=custom --no-owner --no-privileges
```

Validate with `sudo visudo -c`. This grants deploy read access to financial data;
its SSH key must remain private. Do not grant wildcard sudo access or commands
that accept arbitrary output files. Confirm the finance role can access the database
through the local socket before scheduling.

Create ~/.config/centspan-backup.env on the laptop with mode 0600, substituting
your absolute home paths:

```ini
BACKUP_HOST=deploy@209.38.252.91
BACKUP_SSH_KEY=/home/taraba/.ssh/centspan_do_ed25519
BACKUP_RECIPIENT_FILE=/home/taraba/.config/centspan-backups/recipient.txt
BACKUP_IDENTITY_FILE=/home/taraba/.config/centspan-keys/identity.txt
BACKUP_DIRECTORY=/home/taraba/.config/centspan-backups
```

Install the user units after reviewing ExecStart if your checkout path differs:

```bash
install -d "$HOME/.config/systemd/user"
install -m 644 deploy/centspan-backup.service deploy/centspan-backup.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user start centspan-backup.service
systemctl --user status centspan-backup.service
systemctl --user enable --now centspan-backup.timer
systemctl --user list-timers centspan-backup.timer
```

The timer runs daily at 19:00 in the laptop's configured timezone, with up to ten
minutes jitter. A persistent timer catches up when the user manager starts; a
powered-off laptop cannot back up. Inspect failures with
`journalctl --user -u centspan-backup.service`. There is no external alert delivery
configured. Check the latest successful archive daily and after server updates.

Retention policy: keep 30 daily copies and one monthly copy for 12 months. Initially
prune manually only after a newer backup has passed a restore drill. The script
does not delete old backups automatically or risk removing the last usable copy.

### Monthly restore drill

Use an explicitly named disposable local database, never the live app database:

```bash
createdb centspan_restore_drill
set -o pipefail
age -d -i "$HOME/.config/centspan-keys/identity.txt" /absolute/path/to/archive.dump.age \
  | pg_restore --exit-on-error --no-owner --no-privileges --dbname=centspan_restore_drill
```

Compare transaction/account/transfer counts, integer-cent totals, audit history,
reconciliations and migration version with the source snapshot. Inspect the restored
app in an isolated local environment if needed. Do not expose restored sessions;
when performing a real recovery rotate owner credentials and invalidate sessions
before reopening public access. Delete the disposable database after review.

Record archive date, verification outcome and restore outcome without financial
values or credentials. Test a damaged archive and a wrong key: neither may publish
a successful restore. SEC-04 closes only after the separate recovery key, scheduled
backup and latest full restore drill are confirmed.
