from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from ..operations_schemas import OperationsResponse, ProbeResponse
from .errors import ERROR_RESPONSES

router = APIRouter(tags=["system"])
UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"model": ProbeResponse}}


@router.get("/api/health/ready", response_model=ProbeResponse, responses=UNAVAILABLE)
def readiness(request: Request, response: Response):
    ready = request.app.state.readiness.ready()
    response.status_code = 200 if ready else 503
    if not ready:
        response.headers["Retry-After"] = "5"
    return {"status": "ok" if ready else "unavailable"}


@router.get("/api/health/worker", response_model=ProbeResponse, responses=UNAVAILABLE)
def worker_health(request: Request, response: Response):
    status = request.app.state.worker_health.snapshot()["status"]
    response.status_code = 200 if status in {"ok", "starting"} else 503
    if response.status_code == 503:
        response.headers["Retry-After"] = "60"
    return {"status": status if status in {"ok", "starting"} else "unavailable"}


@router.get("/api/operations/health", response_model=OperationsResponse, responses=ERROR_RESPONSES)
def operations(request: Request):
    if not request.state.owner_session["is_admin"]:
        raise HTTPException(403, "Administrator access required")
    return {
        "database_ready": request.app.state.readiness.ready(),
        "worker": request.app.state.worker_health.snapshot(),
    }
