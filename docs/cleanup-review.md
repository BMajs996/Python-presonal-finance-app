# Cleanup and optimization review

Reviewed 2026-10-03. This review covers the current backend repositories and
services, frontend refresh flow, and archived desktop entry point.

## First scoped change

AccountRepository.get previously calculated balances and materialized all accounts
before selecting one in Python. Single-account reads now reuse the same SQL and
domain conversion as the list endpoint, but bind an account-ID predicate so only
the requested account is selected. This also avoids converting unrelated accounts
after account creation. Inactive-account access and missing-account behavior are
preserved. No API/schema changes or production deployment are included.

## Follow-up candidates

The next scoped changes are also implemented: dashboard recent transactions now
skip the unused total-count query while normal pagination retains its count.
Frontend refresh shares dashboard account rows with reference data and an open
accounts view. Navigation to accounts still makes a fresh request. Categories and
ledger-policy requests remain concurrent with the dashboard request; no persistent
account cache was introduced. SQLite query tracing confirms the recent-record
path executes one SELECT, and desktop/mobile browser tests confirm account request
counts and refreshed account creation. PostgreSQL financial parity checks pass.

Remaining candidates:

- Daily and monthly balance histories duplicate the opening-balance query. A
  small shared helper could reduce duplication once date-boundary regression
  coverage is reviewed.
- Account listing uses correlated transaction/transfer aggregates. Compare query
  plans on realistic data before choosing grouped joins or new indexes. No speed
  claim is made without a benchmark.

## Retained deliberately

- FinanceService and FinanceRepository are active API dependencies and heavily
  used by tests. Retiring them is a separate dependency refactor.
- backend/legacy_desktop.py is a documented historical archive, not part of the
  web runtime. Removing it requires a deliberate archival/documentation decision.
- Legacy numeric money fields, SQLite migration/recovery code and existing API
  fields still serve compatibility and recovery paths. They are not dead code.
- Shared frontend escaping, currency and date helpers have active callers.

The review has not established a broad set of safe dead-code deletions. Prefer
measured, focused changes over deleting compatibility code based on file age.
