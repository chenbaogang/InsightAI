from fastapi import Header, HTTPException

from app.auth.service import AuthError, principal_from_token
from app.engine.pipeline import UserCtx
from app.models.meta import new_session


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def http_error(e: AuthError) -> HTTPException:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return HTTPException(status_code=e.status, detail=str(e), headers=headers)


def _principal(token: str):
    session = new_session()
    try:
        return principal_from_token(token, session)
    except AuthError as e:
        raise http_error(e)
    finally:
        session.close()


def current_identity(authorization: str | None = Header(default=None)) -> UserCtx:
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    ctx = _principal(token).to_user_ctx()
    if not ctx.admin and not ctx.dept_filter:
        raise HTTPException(status_code=403, detail="该账号未绑定部门数据权限，请联系管理员配置")
    return ctx


def require_admin(authorization: str | None = Header(default=None)) -> None:
    token = bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    if not _principal(token).admin:
        raise HTTPException(status_code=403, detail="需要管理员角色")

