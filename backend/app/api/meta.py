
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_admin
from app.engine import executor, meta_sync
from app.models.meta import CodeDict, MetaColumn, MetaTable, effective_enum, new_session

router = APIRouter(prefix="/api/meta", dependencies=[Depends(require_admin)])

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _get_table(session, name: str) -> MetaTable:
    t = session.query(MetaTable).filter(MetaTable.name == name).first()
    if not t:
        raise HTTPException(status_code=404, detail=f"表不存在: {name}")
    return t


def _get_column(session, table: str, column: str) -> MetaColumn:
    t = _get_table(session, table)
    c = next((x for x in t.columns if x.name == column), None)
    if not c:
        raise HTTPException(status_code=404, detail=f"列不存在: {table}.{column}")
    return c


class ColumnUpdate(BaseModel):
    enum_dict: dict[str, str] | None = None
    is_sensitive: bool | None = None
    code_dict: str | None = None
    comment: str | None = None


class TableUpdate(BaseModel):
    dept_column: str | None = None
    comment: str | None = None


@router.get("/tables")
async def list_tables():
    session = new_session()
    try:
        out = []
        for t in session.query(MetaTable).order_by(MetaTable.name).all():
            cols = list(t.columns)
            out.append({
                "name": t.name,
                "comment": t.comment,
                "domain": t.domain,
                "dept_column": t.dept_column,
                "n_cols": len(cols),
                "n_enum": sum(1 for c in cols if effective_enum(c)),
                "n_sensitive": sum(1 for c in cols if c.is_sensitive),
            })
        return out
    finally:
        session.close()


class SyncRequest(BaseModel):
    prefixes: list[str] = []


@router.post("/sync")
async def sync_meta(body: SyncRequest):
    prefixes = [p.strip() for p in body.prefixes if p.strip()]
    if not meta_sync.start_async(prefixes):
        raise HTTPException(status_code=409, detail="已有同步任务在运行")
    return meta_sync.get_status()


@router.get("/sync/status")
async def sync_status():
    return meta_sync.get_status()


@router.get("/tables/{name}/columns")
async def list_columns(name: str):
    session = new_session()
    try:
        t = _get_table(session, name)
        return [
            {
                "name": c.name,
                "data_type": c.data_type,
                "comment": c.comment,
                "enum_dict": c.enum_dict or {},
                "is_sensitive": c.is_sensitive,
                "code_dict": c.code_dict.code if c.code_dict else None,
                "effective_enum": effective_enum(c),
            }
            for c in t.columns
        ]
    finally:
        session.close()


@router.put("/columns/{table}/{column}")
def update_column(table: str, column: str, body: ColumnUpdate):
    session = new_session()
    try:
        c = _get_column(session, table, column)
        comment_changed = False
        if body.comment is not None and body.comment.strip() != (c.comment or ""):
            c.comment = body.comment.strip()
            comment_changed = True
        if body.enum_dict is not None:
            bad = [k for k in body.enum_dict if not str(k).strip()]
            if bad:
                raise HTTPException(status_code=422, detail="枚举 key 不能为空")
            c.enum_dict = body.enum_dict or None
        if body.is_sensitive is not None:
            c.is_sensitive = body.is_sensitive
        if body.code_dict is not None:
            code = body.code_dict.strip()
            if code:
                d = session.query(CodeDict).filter(CodeDict.code == code).first()
                if not d:
                    raise HTTPException(status_code=422, detail=f"全局码表不存在: {code}")
                c.code_dict_id = d.id
            else:
                c.code_dict_id = None
        session.commit()
        if comment_changed:
            meta_sync.refresh_vectors(c.table, [c])
        return {
            "ok": True,
            "comment": c.comment,
            "enum_dict": c.enum_dict,
            "is_sensitive": c.is_sensitive,
            "code_dict": c.code_dict.code if c.code_dict else None,
            "effective_enum": effective_enum(c),
        }
    finally:
        session.close()


@router.put("/tables/{name}")
def update_table(name: str, body: TableUpdate):
    session = new_session()
    try:
        t = _get_table(session, name)
        if "dept_column" in body.model_fields_set:
            col = (body.dept_column or "").strip() or None
            if col and not any(c.name == col for c in t.columns):
                raise HTTPException(status_code=422, detail=f"列不存在，无法设为部门列: {col}")
            t.dept_column = col
        comment_changed = False
        if body.comment is not None and body.comment.strip() != (t.comment or ""):
            t.comment = body.comment.strip()
            comment_changed = True
        session.commit()
        if comment_changed:
            meta_sync.refresh_vectors(t)
        return {"ok": True, "dept_column": t.dept_column, "comment": t.comment}
    finally:
        session.close()


@router.get("/probe/{table}/{column}")
async def probe_distinct(table: str, column: str):
    if not (_IDENT_RE.match(table) and _IDENT_RE.match(column)):
        raise HTTPException(status_code=422, detail="非法标识符")
    session = new_session()
    try:
        _get_column(session, table, column)
    finally:
        session.close()
    data = await executor.execute_readonly(
        f"SELECT DISTINCT `{column}` AS v FROM `{table}` WHERE `{column}` IS NOT NULL ORDER BY v LIMIT 50"
    )
    return {"values": [str(r[0]) for r in data["rows"][:50]]}

