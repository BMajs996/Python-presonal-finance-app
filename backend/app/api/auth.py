from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr, field_validator

from ..core.config import settings
from ..services.auth_service import COOKIE, AuthService
from ..services.user_account_service import UserAccountService
from ..user_schemas import PasswordChange, PasswordReset, ProfileUpdate, RegistrationRequest, valid_text

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value):
        return valid_text(value)


class SessionResponse(BaseModel):
    username: str
    csrf_token: str
    user_id: int
    display_name: str
    is_admin: bool


class ProfileResponse(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    phone: str | None
    email_verified_at: str | None
    phone_verified_at: str | None
    is_admin: bool
    created_at: str | None


class SessionSummary(BaseModel):
    session_id: str
    created_at: int
    last_seen: int
    expires_at: int
    current: bool


def source(request):
    return request.client.host if request.client else "unknown"


def identity(row):
    return SessionResponse(
        username=row["username"],
        csrf_token=row["csrf"],
        user_id=row["user_id"],
        display_name=row["display_name"],
        is_admin=bool(row["is_admin"]),
    )


@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, response: Response):
    service = AuthService(request.app.state.database)
    token, csrf = service.login(
        payload.username,
        payload.password.get_secret_value(),
        request.cookies.get(COOKIE),
        source(request),
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
    row = service.session(token)
    if not row:
        raise HTTPException(401, "Sign in again")
    return identity(row)


@router.get("/session", response_model=SessionResponse)
def session(request: Request):
    return identity(request.state.owner_session)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    AuthService(request.app.state.database).logout(request.cookies[COOKIE])
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="strict")


@router.post("/register", status_code=201, response_model=ProfileResponse)
def register(payload: RegistrationRequest, request: Request):
    return UserAccountService(request.app.state.database).register(payload, source(request))


@router.post("/reset-password", status_code=204)
def reset_password(payload: PasswordReset, request: Request):
    UserAccountService(request.app.state.database).reset_password(payload, source(request))


@router.get("/profile", response_model=ProfileResponse)
def profile(request: Request):
    return UserAccountService(request.app.state.database).profile(request.state.owner_session["user_id"])


@router.put("/profile", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdate, request: Request):
    return UserAccountService(request.app.state.database).update_profile(
        request.state.owner_session["user_id"], payload, source(request)
    )


@router.post("/password", status_code=204)
def change_password(payload: PasswordChange, request: Request, response: Response):
    UserAccountService(request.app.state.database).change_password(
        request.state.owner_session["user_id"], payload, source(request)
    )
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="strict")


@router.get("/sessions", response_model=list[SessionSummary])
def sessions(request: Request):
    return AuthService(request.app.state.database).sessions(
        request.state.owner_session["user_id"], request.cookies[COOKIE]
    )


@router.delete("/sessions/{session_id}", status_code=204)
def revoke(session_id: UUID, request: Request):
    AuthService(request.app.state.database).revoke(
        request.state.owner_session["user_id"], str(session_id), source(request)
    )


@router.post("/sessions/revoke-others", status_code=204)
def revoke_others(request: Request):
    AuthService(request.app.state.database).revoke_others(
        request.state.owner_session["user_id"], request.cookies[COOKIE], source(request)
    )
