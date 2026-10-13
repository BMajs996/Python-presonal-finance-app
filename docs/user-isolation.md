# Independent users: ownership foundation

## Scope and rollout gate

This document describes the ownership foundation. The subsequent
[accounts phase](user-accounts.md) adds real per-user credentials, sessions and
administrator-issued recovery. HTTP dependencies obtain the owner from the
server-validated session, never from a request body or query string. There is no
unrestricted signup; review the accounts release gates before inviting users.

## Ownership map

| Data | Ownership root |
| --- | --- |
| Accounts | `accounts.user_id` |
| Transactions and their audit history | Transaction's account |
| Recurring schedules and occurrence claims | Schedule's account |
| Transfers | Both accounts must have the same owner |
| Budgets | `budgets.user_id` |
| Reconciliations and cleared entries | Statement's account, with existing entry guards |
| CSV retry receipts | Server-generated user-specific setting key |

Account ownership and budget ownership cannot be reassigned. Financial entries
cannot move to another owner's account; null/missing account references are rejected.
Account deletion is prohibited, so descendants and historical snapshots retain an
unambiguous owner. Account names and budget categories are unique within an owner,
not across the application. Ownership is enforced by explicit parameterized queries
and database integrity triggers, **not PostgreSQL RLS**. There is no implicit pool
session tenant state to leak between borrowers. A database credential with unrestricted
SQL access can still read all users: this is application isolation, not protection
against a compromised server/database administrator.

Compatibility constructors and trusted owner-only maintenance tools default to
bootstrap user 1. Every HTTP finance/CSV/reconciliation dependency passes an explicit
session owner. Global backup, migration and worker code are privileged system paths;
they must never be exposed as ordinary user endpoints. Operations diagnostics remain
restricted to the current session's administrator role. Only bootstrap user 1 is
initially an administrator.

## Contacts for future registration and notifications

`RegistrationContacts` requires email and international-format phone input. Email
uses email-validator/Pydantic normalization with no network deliverability lookup.
The application's identity key is case-insensitive; it does not strip provider-specific
dots or plus suffixes. Phone input must use a leading `+` and international digits,
with at most 15 digits. This validates format, not number assignment or possession.

`users` stores email, canonical email key and phone separately from verification
timestamps. The legacy owner's contacts remain null; migration does not invent them.
Email notifications, SMS notifications and monthly report preferences default off.
Providing contacts is not consent to delivery and does not verify them. The accounts
phase validates registration input with the shared schema and clears verification
when a contact changes. Future delivery needs verified-contact policies,
explicit preference management, verified destinations, bounded retries/rate limits
and a reviewed provider. No emails, SMS or reports are sent by this release.

No additional contact data is included in financial API responses or log messages.
Contacts remain personal data in the database and encrypted laptop backups; retention,
account deletion and privacy notices must be settled before inviting real users.

## Migration and deployment

SQLite version 8 and PostgreSQL version 3 create bootstrap user 1 and assign existing
accounts/budgets to that user. IDs, integer money, financial dates, relationships,
audit history, currency and CSV retry receipts are preserved. The subsequent accounts
migration revokes legacy sessions and introduces per-user sessions; see the accounts
rollout instructions.

SQLite rebuilds the two ownership roots under a writer reservation. Foreign keys are
disabled only on the dedicated migration connection before beginning its transaction,
validated before commit and restored afterward. Historical explicit indexes/triggers
and AUTOINCREMENT high-water marks are preserved; former global unique indexes become
per-owner constraints. PostgreSQL performs its changes in the existing startup writer
transaction. Failed upgrades roll back their schema and version marker.

Orphan transactions or schedules require owner review before migration; they are not
silently assigned to Main Account. Unknown/gapped migration ledgers remain rejected.

Before production: verified backup, restored-copy rehearsal, compare financial counts
and integer totals/audit rows, then stop old application processes and install the new
runtime requirements. Restart and verify readiness, owner login, balances and worker
status. Do not manually downgrade the schema version to roll back; use the verified
backup with a compatible release. This work has not been deployed to production.

## Worker and capacity

The system worker selects at most 100 due schedules globally, groups only that selection
by owner and invokes scoped repositories. Each schedule retains the existing 100-occurrence
limit and transactional claims. Disabled users are excluded and their active state is
rechecked when the schedule is processed. The existing global financial writer lock,
pool bounds, login hash slots, request-byte limits and HTTP rate protection are retained.
This release makes no new throughput claims. Many users sharing the writer lock require
separate capacity/fairness work before broad registration.

## Verification

SQLite/PostgreSQL tests cover identical names/categories under different owners,
aggregate/report/budget isolation, foreign-ID mutations, deleted history and restore,
CSV preview/duplicate detection/retry IDs, recurring ownership and disabled users,
statement eligibility and direct-SQL ownership violations. Foundation tests inject
principals at the session boundary; accounts tests additionally register and authenticate
real independent users through HTTP and browser flows.

Upgrade tests compare pre/post financial rows, reject orphans without modifying data
and inject failure after ownership DDL to verify rollback and successful retry.
The existing financial-invariant, query-budget, pool and browser suites remain required.
