
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth import jwt
from app.auth import store as auth_store
from app.config import get_settings
from app.models.rbac import Department, Role, User
from app.rbac.security import hash_password, verify_password

logger = logging.getLogger("insightai.auth")

LOGIN_FAILED = "用户名或密码错误"

_DUMMY_HASH = hash_password("insightai-dummy-" + secrets.token_urlsafe(16))

_generated_secret: str | None = None


class AuthError(Exception):
    def __init__(self, msg: str, status: int = 401, retry_after: int | None = None):
        super().__init__(msg)
        self.status = status
        self.retry_after = retry_after


@dataclass
class Principal:

    username: str
    display_name: str
    admin: bool
    dept_code: str | None = None
    dept_name: str | None = None
    data_values: list[str] | None = None
    issued_after: int = 0

    def to_user_ctx(self):
        from app.engine.pipeline import UserCtx

        return UserCtx(
            user_id=self.username,
            dept=self.dept_name or "",
            admin=self.admin,
            data_values=self.data_values or None,
        )

    def public(self) -> dict:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "admin": self.admin,
            "dept_code": self.dept_code,
            "dept_name": self.dept_name,
            "data_values": list(self.data_values or []),
        }


def token_secret() -> str:
    global _generated_secret
    configured = get_settings().token_secret
    if configured:
        return configured
    if _generated_secret is None:
        _generated_secret = secrets.token_urlsafe(32)
        logger.warning("TOKEN_SECRET 未配置，本次启动使用随机密钥；重启后所有登录态失效")
    return _generated_secret


def ensure_user_columns() -> None:
    from sqlalchemy import inspect, text

    from app.models.meta import get_engine

    engine = get_engine()
    try:
        existing = {c["name"] for c in inspect(engine).get_columns("app_user")}
    except Exception:
        return
    adds = []
    if "failed_count" not in existing:
        adds.append("ALTER TABLE app_user ADD COLUMN failed_count INTEGER NOT NULL DEFAULT 0")
    if "locked_until" not in existing:
        adds.append("ALTER TABLE app_user ADD COLUMN locked_until TIMESTAMP")
    if "pwd_changed_at" not in existing:
        adds.append("ALTER TABLE app_user ADD COLUMN pwd_changed_at TIMESTAMP")
    if not adds:
        return
    with engine.begin() as conn:
        for stmt in adds:
            conn.execute(text(stmt))
    logger.warning("已为 app_user 补列: %s", ", ".join(adds))


def _check_rate_limit(client_ip: str) -> None:
    limit = get_settings().login_rate_per_minute
    allowed, retry_after = auth_store.register_attempt(client_ip or "unknown", max(0, limit))
    if not allowed:
        raise AuthError("登录尝试过于频繁，请稍后再试", 429, retry_after)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _register_failure(session: Session, user: User) -> None:
    s = get_settings()
    user.failed_count = (user.failed_count or 0) + 1
    if user.failed_count >= max(1, s.login_max_fails):
        user.locked_until = _now() + timedelta(minutes=s.login_lock_minutes)
        user.failed_count = 0
        logger.warning("账号 %s 连续失败 %d 次，锁定至 %s", user.username, s.login_max_fails, user.locked_until)
    session.commit()


def login(session: Session, username: str, password: str, client_ip: str = "") -> dict:
    _check_rate_limit(client_ip)

    uname = (username or "").strip()
    user = session.query(User).filter_by(username=uname).first() if uname else None
    if not user:
        verify_password(password or "", _DUMMY_HASH)
        raise AuthError(LOGIN_FAILED)
    if not user.active:
        verify_password(password or "", user.pwd_hash)
        raise AuthError("账号已停用，请联系管理员")

    locked_until = user.locked_until
    if locked_until is not None:
        left = (locked_until - _now()).total_seconds()
        if left > 0:
            raise AuthError(f"账号已锁定，请 {int(left // 60) + 1} 分钟后再试", 423, int(left) + 1)
        user.locked_until = None
        user.failed_count = 0

    if not verify_password(password or "", user.pwd_hash):
        _register_failure(session, user)
        raise AuthError(LOGIN_FAILED)

    user.failed_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    session.commit()
    return issue_token(session, user)


def issue_token(session: Session, user: User) -> dict:
    s = get_settings()
    ttl = max(60, s.token_ttl_minutes) * 60
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "username": user.username,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, token_secret())
    principal = load_profile(session, user.username)
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in": ttl,
        "expires_at": (_now() + timedelta(seconds=ttl)).isoformat() + "Z",
        "user": principal.public() if principal else {"username": user.username},
    }


def logout(token: str) -> None:
    try:
        claims = jwt.decode(token, token_secret())
    except jwt.TokenError:
        return
    jti = claims.get("jti")
    if not jti:
        return
    auth_store.revoke(str(jti), float(claims.get("exp", time.time())))


def _is_revoked(jti: str) -> bool:
    return auth_store.is_revoked(jti)


def load_profile(session: Session, username: str) -> Principal | None:
    u = session.query(User).filter_by(username=username, active=True).first()
    if not u:
        return None
    role = session.query(Role).filter_by(code=u.role_code).first()
    dept = session.query(Department).filter_by(code=u.dept_code).first() if u.dept_code else None
    return Principal(
        username=u.username,
        display_name=u.display_name or u.username,
        admin=bool(role and role.admin),
        dept_code=u.dept_code,
        dept_name=(dept.name or dept.code) if dept else None,
        data_values=list(dept.data_values) if dept and dept.data_values else None,
        issued_after=int(u.pwd_changed_at.replace(tzinfo=timezone.utc).timestamp()) if u.pwd_changed_at else 0,
    )


def principal_from_token(token: str, session: Session) -> Principal:
    try:
        claims = jwt.decode(token, token_secret())
    except jwt.TokenError as e:
        raise AuthError(f"登录状态无效：{e}")
    jti = claims.get("jti")
    if jti and _is_revoked(jti):
        raise AuthError("登录状态已注销，请重新登录")
    username = claims.get("username")
    if not username:
        raise AuthError("登录状态无效：缺少用户标识")
    principal = load_profile(session, str(username))
    if not principal:
        raise AuthError("账号不存在或已停用，请重新登录")
    if principal.issued_after and int(claims.get("iat", 0)) < principal.issued_after:
        raise AuthError("口令已修改，请重新登录")
    return principal


def change_password(session: Session, username: str, old_password: str, new_password: str) -> dict:
    from app.rbac.security import password_ok

    uname = (username or "").strip()
    user = session.query(User).filter_by(username=uname).first() if uname else None
    if not user or not user.active:
        raise AuthError("账号不存在或已停用")

    locked_until = user.locked_until
    if locked_until is not None:
        left = (locked_until - _now()).total_seconds()
        if left > 0:
            raise AuthError(f"账号已锁定，请 {int(left // 60) + 1} 分钟后再试", 423, int(left) + 1)
        user.locked_until = None
        user.failed_count = 0

    if not verify_password(old_password or "", user.pwd_hash):
        _register_failure(session, user)
        raise AuthError(LOGIN_FAILED)

    ok, why = password_ok(new_password or "")
    if not ok:
        raise AuthError(why, 400)

    user.pwd_hash = hash_password(new_password)
    user.pwd_changed_at = _now()
    user.failed_count = 0
    user.locked_until = None
    session.commit()
    logger.info("账号 %s 修改了口令，旧登录态已失效", user.username)
    return {"ok": True, "message": "口令已修改，请重新登录"}

