from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, SecretStr

from ..core.config import settings
from ..services.auth_service import COOKIE, AuthService

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)


class SessionResponse(BaseModel):
    username: str
    csrf_token: str


@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, response: Response):
    token, csrf = AuthService(request.app.state.database).login(
        payload.username,
        payload.password.get_secret_value(),
        request.cookies.get(COOKIE),
        request.client.host if request.client else "unknown",
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        max_age=settings.session_seconds,
        path="/",
    )
    return SessionResponse(username=settings.owner_username, csrf_token=csrf)


@router.get("/session", response_model=SessionResponse)
def session(request: Request):
    return SessionResponse(username=settings.owner_username, csrf_token=request.state.owner_session["csrf"])


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    AuthService(request.app.state.database).logout(request.cookies[COOKIE])
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="strict")
