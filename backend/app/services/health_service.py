"""Single-flight, cached readiness. Public probes must not exhaust DB connections."""

import time
from collections.abc import Callable
from threading import Lock

SCHEMA_PROBE = """
    SELECT (SELECT currency FROM accounts WHERE user_id=1 AND name='Main Account') AS currency,
           (SELECT MAX(version) FROM {migration_table}) AS version,
           EXISTS(SELECT amount_cents, date, deleted_at FROM transactions WHERE 1=0),
           EXISTS(SELECT next_date, active, account_id FROM recurring_transactions WHERE 1=0),
           EXISTS(SELECT recurring_id, due_date FROM recurring_occurrences WHERE 1=0),
           EXISTS(SELECT amount_cents FROM transfers WHERE 1=0),
           EXISTS(SELECT monthly_limit_cents FROM budgets WHERE 1=0),
           EXISTS(SELECT opening_balance_cents, active FROM accounts WHERE 1=0),
           EXISTS(SELECT token_hash, user_id, auth_version, session_id FROM auth_sessions WHERE 1=0),
           EXISTS(SELECT attempts FROM auth_login_limit WHERE 1=0),
           EXISTS(SELECT attempts FROM auth_source_limits WHERE 1=0),
           EXISTS(SELECT transaction_id, action FROM transaction_audit WHERE 1=0),
           EXISTS(SELECT closing_balance_cents FROM reconciliations WHERE 1=0),
           EXISTS(SELECT reconciliation_id FROM reconciliation_entries WHERE 1=0),
           EXISTS(SELECT email_key, phone, active, username, password_hash, auth_version
                  FROM users WHERE 1=0),
           EXISTS(SELECT user_id FROM budgets WHERE 1=0)
"""


class ReadinessProbe:
    def __init__(
        self, database, *, cache_seconds: float = 5, monotonic: Callable[[], float] = time.monotonic
    ):
        self.database, self._cache_seconds, self._monotonic = database, cache_seconds, monotonic
        self._lock = Lock()
        self._checked_at = float("-inf")
        self._ready = False

    def ready(self) -> bool:
        if self._monotonic() - self._checked_at < self._cache_seconds:
            return self._ready
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._monotonic() - self._checked_at >= self._cache_seconds:
                try:
                    self._ready = self.database.check_ready()
                except Exception:
                    self._ready = False
                self._checked_at = self._monotonic()
            return self._ready
        finally:
            self._lock.release()
