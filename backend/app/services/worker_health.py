"""Small, process-local recurring health record; no financial payloads."""

import logging
import sqlite3
import time
import traceback
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from threading import Lock

import psycopg

# Inherit the server's handlers so recovery INFO events reach the journal too.
logger = logging.getLogger("uvicorn.error.recurring")


def error_code(error: Exception) -> str:
    if isinstance(error, (psycopg.errors.QueryCanceled, TimeoutError)):
        return "database_timeout"
    if isinstance(error, psycopg.errors.LockNotAvailable) or getattr(error, "sqlite_errorcode", None) in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }:
        return "database_busy"
    if isinstance(error, (sqlite3.IntegrityError, psycopg.IntegrityError, ValueError)):
        return "invalid_data"
    if isinstance(error, (sqlite3.OperationalError, psycopg.OperationalError)):
        return "database_unavailable"
    return "unexpected_error"


def safe_location(error: Exception) -> str:
    # FrameSummary excludes local values; do not log source lines or exception text.
    frames = traceback.extract_tb(error.__traceback__)[-3:]
    return ",".join(f"{frame.name}:{frame.lineno}" for frame in frames) or "unknown"


class WorkerHealth:
    def __init__(
        self,
        *,
        stale_seconds: float = 180,
        failure_threshold: int = 3,
        lag_days: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._lock = Lock()
        self._clock, self._monotonic = clock, monotonic
        self._stale_seconds, self._failure_threshold, self._lag_days = (
            stale_seconds,
            failure_threshold,
            lag_days,
        )
        self._started = monotonic()
        self._run_started = self._started
        self._next_attempt = self._started
        self._alive = True
        self._alerted: set[str] = set()
        self._record: dict = {
            "started_at": clock(),
            "last_started_at": None,
            "last_completed_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "consecutive_failures": 0,
            "last_error_code": None,
            "last_duration_seconds": None,
            "last_created": None,
            "in_progress": False,
            "oldest_due_date": None,
            "lag_days": None,
            "business_date": None,
            "next_attempt_at": None,
        }

    def begin(self) -> None:
        with self._lock:
            self._run_started = self._monotonic()
            self._record.update(in_progress=True, last_started_at=self._clock(), next_attempt_at=None)

    def finish(
        self,
        *,
        delay: float,
        created: int | None = None,
        oldest: date | None = None,
        today: date | None = None,
        failure: str | None = None,
    ) -> None:
        with self._lock:
            now, instant = self._monotonic(), self._clock()
            self._next_attempt = now + delay
            self._record.update(
                in_progress=False,
                last_completed_at=instant,
                last_created=created,
                last_duration_seconds=round(max(0, now - self._run_started), 3),
                oldest_due_date=oldest,
                business_date=today,
                lag_days=None if today is None else (today - oldest).days if oldest else 0,
                next_attempt_at=instant + timedelta(seconds=delay),
            )
            if failure:
                self._record.update(last_failure_at=instant, last_error_code=failure)
                self._record["consecutive_failures"] += 1
            else:
                self._record.update(last_success_at=instant, consecutive_failures=0)

    def stopped(self) -> None:
        with self._lock:
            self._alive = False
            self._record.update(in_progress=False, next_attempt_at=None)

    def snapshot(self) -> dict:
        with self._lock:
            record, now = self._record.copy(), self._monotonic()
            reasons = []
            if not self._alive:
                reasons.append("worker_stopped")
            if record["in_progress"] and now - self._run_started > self._stale_seconds:
                reasons.append("processing_stalled")
            elif not record["in_progress"] and now > self._next_attempt + self._stale_seconds:
                reasons.append("heartbeat_stale")
            if record["consecutive_failures"]:
                reasons.append(
                    "repeated_failures"
                    if record["consecutive_failures"] >= self._failure_threshold
                    else "retrying"
                )
            if record["lag_days"] is not None and record["lag_days"] >= self._lag_days:
                reasons.append("backlog_lag")
            status = (
                "stopped"
                if not self._alive
                else "degraded"
                if reasons
                else ("starting" if record["last_completed_at"] is None else "ok")
            )
            return {**record, "status": status, "reasons": reasons}

    def observe(self) -> None:
        snapshot = self.snapshot()
        reasons = set(snapshot["reasons"]) - {"retrying"}
        with self._lock:
            if reasons == self._alerted:
                return
            previous, self._alerted = self._alerted, reasons
        if reasons:
            logger.error(
                "Recurring health alert reasons=%s failures=%s",
                ",".join(sorted(reasons)),
                snapshot["consecutive_failures"],
            )
        elif previous:
            logger.info("Recurring health recovered")
