import secrets

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, RedirectResponse, Response

from ..domain import business_date
from ..services.auth_service import COOKIE, AuthService
from .config import settings


class ConfiguredCORS:
    """Use the explicit configured allowlist, including in isolated app tests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        middleware = CORSMiddleware(
            self.app,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
            max_age=600,
        )
        await middleware(scope, receive, send)


class ConfiguredHosts:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        middleware = TrustedHostMiddleware(
            self.app, allowed_hosts=settings.allowed_host_list, www_redirect=False
        )
        await middleware(scope, receive, send)


class OwnerAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        with business_date.snapshot():
            return await self._dispatch(request, call_next)

    async def _dispatch(self, request, call_next):
        if settings.environment == "production" and request.url.scheme != "https":
            return JSONResponse({"detail": "HTTPS required"}, status_code=400)
        path = request.url.path
        protected = (path.startswith("/api/") and path not in {"/api/health", "/api/auth/login"}) or path in {
            "/",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
            "/openapi.json",
        }
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        response: Response | None = None
        if path.startswith("/api/") and unsafe:
            if request.headers.get("origin") not in settings.cors_origin_list:
                response = JSONResponse({"detail": "Origin not permitted"}, status_code=403)
        if protected and response is None:
            session = await run_in_threadpool(
                AuthService(request.app.state.database).session, request.cookies.get(COOKIE)
            )
            if session is None:
                response = (
                    RedirectResponse("/login", status_code=303)
                    if path == "/"
                    else JSONResponse({"detail": "Authentication required"}, status_code=401)
                )
            elif unsafe and not secrets.compare_digest(
                request.headers.get("x-csrf-token", "").encode(), session["csrf"].encode()
            ):
                response = JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
            else:
                request.state.owner_session = session
        if response is None:
            response = await call_next(request)
        if protected or path.startswith("/api/auth/") or path == "/login":
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"
        if path in {"/", "/login"} or path.startswith("/assets/"):
            response.headers["Content-Security-Policy-Report-Only"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
