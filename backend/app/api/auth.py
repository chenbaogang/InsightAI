
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import bearer_token, http_error
from app.auth import service
from app.auth.service import AuthError
from app.models.meta import new_session

router = APIRouter(prefix="/api/auth")


class LoginReq(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordReq(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def login(req: LoginReq, request: Request):
    session = new_session()
    try:
        try:
            return service.login(session, req.username, req.password, _client_ip(request))
        except AuthError as e:
            raise http_error(e)
    finally:
        session.close()


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    token = bearer_token(authorization)
    if token:
        service.logout(token)
    return {"ok": True}


@router.get("/me")
async def me(authorization: str | None = Header(default=None)):
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    session = new_session()
    try:
        try:
            principal = service.principal_from_token(token, session)
        except AuthError as e:
            raise http_error(e)
    finally:
        session.close()
    return principal.public()


@router.put("/password")
async def put_password(req: PasswordReq, authorization: str | None = Header(default=None)):
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    session = new_session()
    try:
        try:
            principal = service.principal_from_token(token, session)
            result = service.change_password(
                session, principal.username, req.old_password, req.new_password
            )
        except AuthError as e:
            raise http_error(e)
    finally:
        session.close()
    service.logout(token)
    return result

