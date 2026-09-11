from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field

from app.services.auth_service import AuthService
from app.services.password_recovery_mailer import PasswordRecoveryMailer
from app.services.password_recovery_service import PasswordRecoveryService


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    displayName: str | None = Field(default=None, max_length=120)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=12, max_length=256)


class PasswordRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)


class PasswordRecoveryResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512)
    newPassword: str = Field(min_length=12, max_length=256)


def _service() -> AuthService:
    try:
        return AuthService()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenticación no configurada de forma segura.",
        ) from exc


def _recovery_service() -> PasswordRecoveryService:
    return PasswordRecoveryService()


def _recovery_mailer() -> PasswordRecoveryMailer:
    try:
        return PasswordRecoveryMailer()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recuperación de cuenta no configurada de forma segura.",
        ) from exc


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales no válidas.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> dict[str, Any]:
    service = _service()
    try:
        account = service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.displayName,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "account_created",
        "account": account,
    }


@router.post("/token")
def token(
    request: Request,
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> dict[str, Any]:
    service = _service()
    client_id = request.client.host if request.client is not None else "unknown"
    rate_key = service.login_rate_key(email=form.username, client_id=client_id)
    rate = service.consume_login_attempt(rate_key=rate_key)
    if not bool(rate["allowed"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos de autenticación. Inténtalo más tarde.",
            headers={"Retry-After": str(service.LOGIN_WINDOW_SECONDS)},
        )

    account = service.authenticate(email=form.username, password=form.password)
    if account is None:
        response.headers["X-RateLimit-Limit"] = str(rate["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate["remaining"])
        raise _credentials_error()

    service.clear_login_attempts(rate_key=rate_key)
    access_token = service.create_access_token(
        user_id=int(account["id"]),
        email=str(account["email"]),
    )
    response.headers["X-RateLimit-Limit"] = str(service.LOGIN_ATTEMPT_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(service.LOGIN_ATTEMPT_LIMIT)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": service.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/recovery/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_recovery(
    payload: PasswordRecoveryRequest,
    request: Request,
    response: Response,
) -> dict[str, str]:
    mailer = _recovery_mailer()
    service = _recovery_service()
    client_id = request.client.host if request.client is not None else "unknown"
    rate_key = service.recovery_rate_key(email=payload.email, client_id=client_id)
    rate = service.consume_recovery_attempt(rate_key=rate_key)
    if not bool(rate["allowed"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes de recuperación. Inténtalo más tarde.",
            headers={"Retry-After": str(service.RECOVERY_WINDOW_SECONDS)},
        )
    challenge = service.request(email=payload.email)
    if challenge is not None:
        try:
            mailer.send(challenge)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo entregar la recuperación de cuenta.",
            ) from exc
    response.headers["X-RateLimit-Limit"] = str(rate["limit"])
    response.headers["X-RateLimit-Remaining"] = str(rate["remaining"])
    return {
        "status": "recovery_requested",
        "message": "Si existe una cuenta válida para ese email, se enviarán instrucciones de recuperación.",
    }


@router.post("/recovery/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: PasswordRecoveryResetRequest) -> Response:
    service = _recovery_service()
    try:
        changed = service.reset(
            token=payload.token,
            new_password=payload.newPassword,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de recuperación no válido o caducado.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def current_account(
    bearer_token: Annotated[str, Depends(oauth2_scheme)],
) -> dict[str, Any]:
    service = _service()
    account = service.account_from_token(bearer_token)
    if account is None:
        raise _credentials_error()
    return account


@router.get("/me")
def me(account: Annotated[dict[str, Any], Depends(current_account)]) -> dict[str, Any]:
    return {
        "status": "authenticated",
        "account": account,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    bearer_token: Annotated[str, Depends(oauth2_scheme)],
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> Response:
    del account
    service = _service()
    if not service.revoke_access_token(bearer_token):
        raise _credentials_error()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> Response:
    service = _service()
    service.revoke_all_sessions(user_id=int(account["id"]))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    account: Annotated[dict[str, Any], Depends(current_account)],
) -> Response:
    service = _service()
    try:
        changed = service.change_password(
            user_id=int(account["id"]),
            current_password=payload.currentPassword,
            new_password=payload.newPassword,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not changed:
        raise _credentials_error()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
