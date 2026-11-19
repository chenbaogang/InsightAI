
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from app.api.deps import require_admin
from app.models.meta import new_session
from app.models.rbac import Department, Role, User
from app.rbac import service
from app.rbac.service import RbacError

router = APIRouter(prefix="/api/rbac", dependencies=[Depends(require_admin)])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except RbacError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


class DeptCreate(BaseModel):
    code: str
    name: str = ""
    data_values: list[str] = []
    parent_code: str | None = None


class DeptUpdate(BaseModel):
    name: str | None = None
    data_values: list[str] | None = None
    parent_code: str | None = None
    active: bool | None = None


class RoleCreate(BaseModel):
    code: str
    name: str = ""
    admin: bool = False
    comment: str = ""


class RoleUpdate(BaseModel):
    name: str | None = None
    admin: bool | None = None
    comment: str | None = None


class UserCreate(BaseModel):
    username: str
    display_name: str = ""
    dept_code: str | None = None
    role_code: str = "user"
    password: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    dept_code: str | None = None
    role_code: str | None = None
    active: bool | None = None
    password: str | None = None


def _user_counts(col: str) -> dict[str, int]:
    session = new_session()
    try:
        rows = session.query(getattr(User, col), func.count(User.id)).group_by(getattr(User, col)).all()
        return {code: n for code, n in rows if code}
    finally:
        session.close()


def _dept_out(d: Department) -> dict:
    counts = _user_counts("dept_code")
    return {
        "code": d.code,
        "name": d.name,
        "parent_code": d.parent_code,
        "data_values": list(d.data_values or []),
        "active": d.active,
        "n_users": counts.get(d.code, 0),
    }


def _role_out(r: Role) -> dict:
    counts = _user_counts("role_code")
    return {
        "code": r.code,
        "name": r.name,
        "admin": r.admin,
        "builtin": r.builtin,
        "comment": r.comment,
        "n_users": counts.get(r.code, 0),
    }


def _user_out(u: User) -> dict:
    session = new_session()
    try:
        depts = {d.code: d for d in session.query(Department).all()}
        roles = {r.code: r for r in session.query(Role).all()}
    finally:
        session.close()
    d = depts.get(u.dept_code or "")
    r = roles.get(u.role_code)
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "dept_code": u.dept_code,
        "dept_name": d.name if d else None,
        "data_values": list(d.data_values or []) if d else [],
        "role_code": u.role_code,
        "role_name": r.name if r else u.role_code,
        "is_admin": bool(r and r.admin),
        "active": u.active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/departments")
async def list_departments():
    session = new_session()
    try:
        return [_dept_out(d) for d in session.query(Department).order_by(Department.code).all()]
    finally:
        session.close()


@router.post("/departments")
async def create_department(body: DeptCreate):
    session = new_session()
    try:
        d = _run(service.create_dept, session, body.code, body.name, body.data_values, body.parent_code)
        return _dept_out(d)
    finally:
        session.close()


@router.put("/departments/{code}")
async def update_department(code: str, body: DeptUpdate):
    session = new_session()
    try:
        d = _run(service.update_dept, session, code, **body.model_dump(exclude_unset=True))
        return _dept_out(d)
    finally:
        session.close()


@router.delete("/departments/{code}")
async def delete_department(code: str):
    session = new_session()
    try:
        _run(service.delete_dept, session, code)
        return {"ok": True}
    finally:
        session.close()


@router.get("/roles")
async def list_roles():
    session = new_session()
    try:
        return [_role_out(r) for r in session.query(Role).order_by(Role.id).all()]
    finally:
        session.close()


@router.post("/roles")
async def create_role(body: RoleCreate):
    session = new_session()
    try:
        r = _run(service.create_role, session, body.code, body.name, body.admin, body.comment)
        return _role_out(r)
    finally:
        session.close()


@router.put("/roles/{code}")
async def update_role(code: str, body: RoleUpdate):
    session = new_session()
    try:
        r = _run(service.update_role, session, code, **body.model_dump(exclude_unset=True))
        return _role_out(r)
    finally:
        session.close()


@router.delete("/roles/{code}")
async def delete_role(code: str):
    session = new_session()
    try:
        _run(service.delete_role, session, code)
        return {"ok": True}
    finally:
        session.close()


@router.get("/users")
async def list_users():
    session = new_session()
    try:
        users = session.query(User).order_by(User.username).all()
        return [_user_out(u) for u in users]
    finally:
        session.close()


@router.post("/users")
async def create_user(body: UserCreate):
    session = new_session()
    try:
        u, temp_pwd = _run(
            service.create_user, session, body.username,
            display_name=body.display_name, dept_code=body.dept_code,
            role_code=body.role_code, password=body.password,
        )
        out = _user_out(u)
        if temp_pwd:
            out["initial_password"] = temp_pwd
        return out
    finally:
        session.close()


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UserUpdate):
    session = new_session()
    try:
        u = _run(service.update_user, session, user_id, **body.model_dump(exclude_unset=True))
        return _user_out(u)
    finally:
        session.close()


@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    session = new_session()
    try:
        _run(service.delete_user, session, user_id)
        return {"ok": True}
    finally:
        session.close()

