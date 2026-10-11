from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class ProbeResponse(BaseModel):
    status: Literal["ok", "starting", "unavailable"]


class WorkerHealthResponse(BaseModel):
    status: Literal["starting", "ok", "degraded", "stopped"]
    reasons: list[str]
    started_at: datetime
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    last_error_code: str | None
    last_duration_seconds: float | None
    last_created: int | None
    in_progress: bool
    oldest_due_date: date | None
    lag_days: int | None
    business_date: date | None
    next_attempt_at: datetime | None


class OperationsResponse(BaseModel):
    database_ready: bool
    worker: WorkerHealthResponse
