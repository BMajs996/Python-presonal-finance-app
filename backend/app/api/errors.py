from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..domain.errors import Conflict, DomainError, NotFound
from ..schemas import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (400, 404, 409)
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        status_code = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 400
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})
