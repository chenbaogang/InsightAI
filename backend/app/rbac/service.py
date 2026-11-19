
import logging
import re

from sqlalchemy.orm import Session

from app.models.rbac import Department, Role, User
from app.rbac.security import hash_password, password_ok, random_password

logger = logging.getLogger("insightai.rbac")

ROLE_ADMIN = "admin"
ROLE_USER = "user"

_IDENT_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff\- ]{1,64}$")
_MAX_DATA_VALUES = 50


class RbacError(Exception):

    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def _check_ident(value: str, what: str) -> str:
    v = (value or "").strip()
    if not v:
        raise RbacError(f"{what}不能为空")
    if not _IDENT_RE.match(v):
        raise RbacError(f"{what}只能包含中英文、数字、下划线、连字符或空格，且不超过 64 字符")
    return v


def normalize_data_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    if len(values) > _MAX_DATA_VALUES:
        raise RbacError(f"单位码集合最多 {_MAX_DATA_VALUES} 个")
    out, seen = [], set()
    for raw in values:
        v = _check_ident(str(raw), "单位码")
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def seed_defaults(session: Session, admin_password: str | None = None) -> dict:
    info: dict = {"created_admin": None}
    for code, name, is_admin, comment in [
        (ROLE_ADMIN, "管理员", True, "可进管理页：语义层、部门/角色/用户维护"),
        (ROLE_USER, "普通用户", False, "仅提问与查看自己的会话"),
    ]:
        if not session.query(Role).filter_by(code=code).first():
            session.add(Role(code=code, name=name, admin=is_admin, builtin=True, comment=comment))
    session.commit()

    has_admin = (
        session.query(User)
        .join(Role, User.role_code == Role.code)
        .filter(Role.admin.is_(True), User.active.is_(True))
        .first()
    )
    if not has_admin:
        pwd = admin_password or random_password()
        if admin_password:
            ok, why = password_ok(pwd)
            if not ok:
                raise RbacError(f"初始管理员密码不符合要求: {why}")
        admin = User(
            username="admin",
            display_name="系统管理员",
            role_code=ROLE_ADMIN,
            active=True,
            pwd_hash=hash_password(pwd),
        )
        session.add(admin)
        session.commit()
        info["created_admin"] = {"username": admin.username, "password": pwd}
        logger.warning("已创建初始管理员 admin，初始口令仅本次可见: %s", pwd)
    return info


def count_active_admins(session: Session) -> int:
    return (
        session.query(User)
        .join(Role, User.role_code == Role.code)
        .filter(Role.admin.is_(True), User.active.is_(True))
        .count()
    )


def get_dept(session: Session, code: str) -> Department | None:
    return session.query(Department).filter_by(code=code).first()


def get_role(session: Session, code: str) -> Role | None:
    return session.query(Role).filter_by(code=code).first()


def validate_dept(session: Session, code: str) -> Department:
    d = get_dept(session, code)
    if not d:
        raise RbacError(f"部门不存在: {code}", 422)
    return d


def validate_role(session: Session, code: str) -> Role:
    r = get_role(session, code)
    if not r:
        raise RbacError(f"角色不存在: {code}", 422)
    return r


def create_dept(session: Session, code: str, name: str, data_values: list[str] | None,
                parent_code: str | None = None) -> Department:
    code = _check_ident(code, "部门编码")
    if get_dept(session, code):
        raise RbacError(f"部门编码已存在: {code}", 409)
    if parent_code:
        parent_code = _check_ident(parent_code, "上级部门编码")
        validate_dept(session, parent_code)
    d = Department(
        code=code,
        name=(name or "").strip() or code,
        data_values=normalize_data_values(data_values),
        parent_code=parent_code,
        active=True,
    )
    session.add(d)
    session.commit()
    return d


def update_dept(session: Session, code: str, *, name: str | None = None,
               data_values: list[str] | None = None, parent_code: str | None = ...,
               active: bool | None = None) -> Department:
    d = validate_dept(session, code)
    if name is not None:
        d.name = name.strip() or d.code
    if data_values is not None:
        d.data_values = normalize_data_values(data_values)
    if parent_code is not ...:
        pc = (parent_code or "").strip() or None
        if pc == d.code:
            raise RbacError("上级部门不能是自己")
        if pc:
            validate_dept(session, pc)
        d.parent_code = pc
    if active is not None:
        if not active and session.query(User).filter_by(dept_code=d.code, active=True).first():
            raise RbacError(f"仍有启用用户归属该部门，无法停用: {d.code}", 409)
        d.active = active
    session.commit()
    return d


def delete_dept(session: Session, code: str) -> None:
    d = validate_dept(session, code)
    if session.query(User).filter_by(dept_code=d.code).first():
        raise RbacError(f"部门下仍有用户，无法删除: {d.code}", 409)
    if session.query(Department).filter_by(parent_code=d.code).first():
        raise RbacError(f"存在下级部门，无法删除: {d.code}", 409)
    session.delete(d)
    session.commit()


def create_role(session: Session, code: str, name: str, admin: bool, comment: str = "") -> Role:
    code = _check_ident(code, "角色编码")
    if get_role(session, code):
        raise RbacError(f"角色编码已存在: {code}", 409)
    r = Role(code=code, name=(name or "").strip() or code, admin=bool(admin),
             builtin=False, comment=comment or "")
    session.add(r)
    session.commit()
    return r


def update_role(session: Session, code: str, *, name: str | None = None,
                admin: bool | None = None, comment: str | None = None) -> Role:
    r = validate_role(session, code)
    if admin is not None and bool(admin) != r.admin:
        if r.builtin and r.code == ROLE_ADMIN:
            raise RbacError("内置管理员角色不可取消管理员属性", 409)
        if not admin:
            still_admin = session.query(User).filter_by(role_code=r.code, active=True).count()
            if r.admin and still_admin and count_active_admins(session) - still_admin < 1:
                raise RbacError("取消该角色管理员属性后将没有可用管理员", 409)
        r.admin = bool(admin)
    if name is not None:
        r.name = name.strip() or r.code
    if comment is not None:
        r.comment = comment
    session.commit()
    return r


def delete_role(session: Session, code: str) -> None:
    r = validate_role(session, code)
    if r.builtin:
        raise RbacError(f"内置角色不可删除: {r.code}", 409)
    if session.query(User).filter_by(role_code=r.code).first():
        raise RbacError(f"角色下仍有用户，无法删除: {r.code}", 409)
    session.delete(r)
    session.commit()


def create_user(session: Session, username: str, *, display_name: str = "", dept_code: str | None,
                role_code: str, password: str | None = None) -> tuple[User, str | None]:
    username = _check_ident(username, "用户名")
    if session.query(User).filter_by(username=username).first():
        raise RbacError(f"用户名已存在: {username}", 409)
    validate_role(session, role_code)
    if dept_code:
        validate_dept(session, dept_code)
    if password is not None:
        ok, why = password_ok(password)
        if not ok:
            raise RbacError(why)
    pwd = password or random_password()
    u = User(
        username=username,
        display_name=(display_name or "").strip() or username,
        dept_code=(dept_code or "").strip() or None,
        role_code=role_code,
        pwd_hash=hash_password(pwd),
        active=True,
    )
    session.add(u)
    session.commit()
    return u, (pwd if password is None else None)


def update_user(session: Session, user_id: int, *, display_name: str | None = None,
                dept_code: str | None = ..., role_code: str | None = None,
                active: bool | None = None, password: str | None = None) -> User:
    u = session.get(User, user_id)
    if not u:
        raise RbacError(f"用户不存在: {user_id}", 404)
    if dept_code is not ...:
        dc = (dept_code or "").strip() or None
        if dc:
            validate_dept(session, dc)
        u.dept_code = dc
    if role_code is not None:
        new_role = validate_role(session, role_code)
        demoting = u.role_code != role_code and _is_admin_role(session, u.role_code)
        if demoting and not new_role.admin and count_active_admins(session) <= 1:
            raise RbacError("必须保留至少一个启用的管理员", 409)
        u.role_code = role_code
    if active is not None:
        if not active and _is_admin_role(session, u.role_code) and count_active_admins(session) <= 1:
            raise RbacError("必须保留至少一个启用的管理员", 409)
        u.active = active
    if display_name is not None:
        u.display_name = display_name.strip() or u.username
    if password:
        ok, why = password_ok(password)
        if not ok:
            raise RbacError(why)
        u.pwd_hash = hash_password(password)
    session.commit()
    return u


def _is_admin_role(session: Session, role_code: str) -> bool:
    r = get_role(session, role_code)
    return bool(r and r.admin)


def delete_user(session: Session, user_id: int) -> None:
    u = session.get(User, user_id)
    if not u:
        raise RbacError(f"用户不存在: {user_id}", 404)
    if _is_admin_role(session, u.role_code) and count_active_admins(session) <= 1:
        raise RbacError("必须保留至少一个启用的管理员", 409)
    session.delete(u)
    session.commit()

