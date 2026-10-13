# Invite-only accounts, sessions and manual recovery

## Scope

Users now have independent credentials and financial data. Registration requires a
single-use invitation issued through the trusted-host CLI. There is no unrestricted
signup, public invitation API or email-based forgot-password endpoint. Email/SMS
delivery, contact verification, 2FA and Google OAuth are **not implemented**. Manual
administrator-issued recovery is the agreed mechanism until an email provider is ready.

## Model and existing owner

SQLite migration 9 and PostgreSQL migration 4 add username/canonical key, display name,
Argon2id password hash, credential version, bootstrap fingerprint, administrator flag
and creation timestamp. New usernames use 3-50 ASCII letters/digits/dots/underscores/
hyphens and are unique case-insensitively. Login accepts username or email.

Registration requires name, email, international phone, 15-1024 character password
and invitation. The invitation is bound to the canonical email but manual delivery
does not verify email/phone possession. Verification timestamps stay empty and all
notifications/report preferences stay off. Roles, owner IDs and verification flags
cannot be supplied through registration/profile input. New members are not admins.
Registration consumes the invite and creates the user and zero-balance Main Account
atomically. Failed inserts roll back the token claim; financial history is unchanged.

Startup seeds configured owner credentials into user 1. OWNER_PASSWORD_HASH remains
required in production for bootstrap/recovery. An unchanged configuration fingerprint
does not overwrite a password changed through the UI. Changing the configured hash
via setup_owner and restarting resets only user 1 and revokes their sessions. Avoid
renaming OWNER_USERNAME to an existing member username. Pre-user sessions are revoked
on upgrade: everyone must sign in again. Later restarts are idempotent.

## Local administration

Run from the repository root with the same environment/database as the app:

```bash
source .venv/bin/activate
python -m backend.app.manage_users invite alice@example.com
python -m backend.app.manage_users list
python -m backend.app.manage_users reset alice
python -m backend.app.manage_users disable alice
python -m backend.app.manage_users enable alice
python -m backend.app.manage_users revoke-all
```

Invite links expire after 48 hours; recovery links after 30 minutes. Reset takes an
existing username. Reissuing replaces the older link for that purpose/recipient.
Only token hashes are stored. Concurrent redemption succeeds once; at most 1,000
pending links are allowed, and issuance cleans up expired records.

**Links are bearer credentials.** Verify recovery requesters manually and share links
only through a trusted private channel. Do not paste links in public issues, this
chat, logs or shared documents. The URL fragment is not sent in HTTP requests; the
browser removes it from the current history entry and keeps it in memory only.
Reloading a form requires reopening its original link. Do not capture issuance stdout.

Disable/enable revokes previous sessions and recovery links and bumps the credential
version. Enabling does not resurrect sessions. The bootstrap admin cannot be disabled
through this command. Financial data/schedules remain; the worker skips disabled users.
Already admitted requests may finish: disabling is not in-flight request cancellation.

For a suspected compromise, disable the member first, then issue a fresh reset link.
The new administrator-issued link changes the password while the account stays
disabled; it does not enable it. Confirm recovery before running enable. Enabling
before redemption invalidates the pending link, so issue a replacement if needed.

After restoring a full database backup, run `revoke-all` before exposing the app to
the network. It invalidates every user's restored sessions and outstanding account
links. Rotating only the owner password is no longer sufficient. Review/reset any
password changes lost by the restore or credentials suspected of compromise before
reopening access; session revocation does not change stored passwords.

## Production administration

Use the service's environment and runtime identity, not an unconfigured shell which
could open a different development database. For the existing systemd deployment:

```bash
sudo systemd-run --quiet --wait --pipe --collect --uid=finance \
  --property=WorkingDirectory=/opt/finance-dashboard \
  --property=EnvironmentFile=/etc/finance-dashboard/production.env \
  /opt/finance-dashboard/.venv/bin/python -m backend.app.manage_users invite alice@example.com
```

Replace the last arguments with reset/list/disable/enable as above. --pipe connects
the credential output to the terminal instead of ordinary journal output. These
examples do not deploy or change the actual server.

## Sessions and profile

Opaque cookies remain Secure/HttpOnly/SameSite=Strict in production, with CSRF/origin
checks and idle/absolute expiry. Sessions now bind user ID and credential version;
at most five are active per user. Session lists expose non-bearer UUIDs and timestamps,
never token hashes or CSRF secrets. Users can revoke their own sessions or all other
sessions without affecting another user. Administrator diagnostics require an admin
role; administrator financial queries remain scoped to their own data.

Profile allows name/contact changes after current-password confirmation. Changed
contacts lose verification/preference state. Password changes/resets revoke all
target-user sessions and outstanding reset links and do not automatically sign in.
No passwords/hashes are returned by APIs. Contact retention, privacy notices and
deletion obligations need review before onboarding real users.

## Capacity and release gates

Hashing/verification shares two slots. Database-backed 60-second reservations limit
login/registration/recovery/sensitive actions to 10 requests per source, 30 per account
or target, and 100 globally. Username/email aliases share an account key. 429 includes
Retry-After; pool exhaustion stays a sanitized 503. Unknown users use a dummy hash.
One source's ten failed attempts do not exhaust the wider account reservation; a
distributed attack can temporarily throttle a target, and shared-NAT bursts can hit
source limits. Measure capacity before changing limits.

Nginx 16 KiB/5-second auth body/read limits now cover login, register, reset-password,
password and profile. **Install the updated rendered proxy config before invitations.**
Keep the app port private. No alternate public listener/body-buffering wrapper is added.

Sanitized security events contain IDs, fixed event names and UTC epoch timestamps,
not contacts, passwords, tokens or raw IPs. Retention is capped at 90 days and about
10,000 latest events, separate from immutable financial audit history.

Before production: verified backup, restored-copy rehearsal, compare financial rows,
amounts/history, then check bootstrap/member login, isolation, worker and readiness.
Tests cover real member HTTP sessions, foreign finance/session IDs, privilege tampering,
expired/replayed links, concurrent redemption, changes across restart, recovery and
disable/enable. Desktop/mobile workflows exercise the forms on both database backends.

This work has not been deployed. Automatic email recovery/verification is not available.
