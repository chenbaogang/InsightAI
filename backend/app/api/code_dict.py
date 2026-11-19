import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from app.api.deps import require_admin
from app.models.meta import CodeDict, MetaColumn, MetaTable, new_session

router = APIRouter(prefix="/api/code-dicts", dependencies=[Depends(require_admin)])

_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _validate_entries(entries: dict[str, str]) -> None:
    bad = [k for k in entries if not str(k).strip()]
    if bad:
        raise HTTPException(status_code=422, detail="枚举 key 不能为空")


class DictCreate(BaseModel):
    code: str
    name: str = ""
    entries: dict[str, str] = {}
    comment: str = ""


class DictUpdate(BaseModel):
    name: str | None = None
    entries: dict[str, str] | None = None
    comment: str | None = None


def _get(session, code: str) -> CodeDict:
    d = session.query(CodeDict).filter(CodeDict.code == code).first()
    if not d:
        raise HTTPException(status_code=404, detail=f"全局码表不存在: {code}")
    return d


def _dump(session, d: CodeDict) -> dict:
    n = session.query(MetaColumn).filter(MetaColumn.code_dict_id == d.id).count()
    return {"code": d.code, "name": d.name, "entries": d.entries or {}, "comment": d.comment, "n_bindings": n}


@router.get("")
async def list_dicts():
    session = new_session()
    try:
        return [_dump(session, d) for d in session.query(CodeDict).order_by(CodeDict.code).all()]
    finally:
        session.close()


@router.post("")
async def create_dict(body: DictCreate):
    if not _CODE_RE.match(body.code):
        raise HTTPException(status_code=422, detail="编码仅限字母/数字/下划线，1~64 位")
    _validate_entries(body.entries)
    session = new_session()
    try:
        if session.query(CodeDict).filter(CodeDict.code == body.code).first():
            raise HTTPException(status_code=409, detail=f"编码已存在: {body.code}")
        d = CodeDict(code=body.code, name=body.name, entries=body.entries, comment=body.comment)
        session.add(d)
        session.commit()
        return _dump(session, d)
    finally:
        session.close()


@router.put("/{code}")
async def update_dict(code: str, body: DictUpdate):
    session = new_session()
    try:
        d = _get(session, code)
        if body.name is not None:
            d.name = body.name
        if body.entries is not None:
            _validate_entries(body.entries)
            d.entries = body.entries
        if body.comment is not None:
            d.comment = body.comment
        session.commit()
        return _dump(session, d)
    finally:
        session.close()


@router.delete("/{code}")
async def delete_dict(code: str):
    session = new_session()
    try:
        d = _get(session, code)
        bound = session.query(MetaColumn).filter(MetaColumn.code_dict_id == d.id).all()
        for c in bound:
            c.code_dict_id = None
        session.delete(d)
        session.commit()
        return {"ok": True, "n_unbound": len(bound)}
    finally:
        session.close()


class BindTarget(BaseModel):
    table: str
    column: str


class BindRequest(BaseModel):
    targets: list[BindTarget]


@router.get("/{code}/match")
async def match_columns(code: str, column: str):
    names = [n.strip().lower() for n in column.split(",") if n.strip()]
    if not names:
        raise HTTPException(status_code=422, detail="请输入列名")
    session = new_session()
    try:
        _get(session, code)
        rows = (
            session.query(MetaColumn, MetaTable.name, MetaTable.comment)
            .join(MetaTable, MetaColumn.table_id == MetaTable.id)
            .filter(func.lower(MetaColumn.name).in_(names))
            .order_by(MetaTable.name, MetaColumn.name)
            .all()
        )
        return [
            {
                "table": tname, "table_comment": tcomment, "column": c.name,
                "comment": c.comment, "bound_dict": c.code_dict.code if c.code_dict else None,
            }
            for c, tname, tcomment in rows
        ]
    finally:
        session.close()


@router.post("/{code}/bind")
async def bind_columns(code: str, body: BindRequest):
    if not body.targets:
        raise HTTPException(status_code=422, detail="未选择任何列")
    session = new_session()
    try:
        d = _get(session, code)
        n = 0
        for t in body.targets:
            c = (
                session.query(MetaColumn)
                .join(MetaTable, MetaColumn.table_id == MetaTable.id)
                .filter(MetaTable.name == t.table, MetaColumn.name == t.column)
                .first()
            )
            if c:
                c.code_dict_id = d.id
                n += 1
        session.commit()
        return {"ok": True, "n_bound": n}
    finally:
        session.close()