from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from app.api.deps import require_admin
from app.models.meta import MetaTable, new_session
from app.models.metric import Metric

router = APIRouter(prefix="/api/metrics", dependencies=[Depends(require_admin)])

_GRAINS = {"daily", "monthly", "yearly", "none"}


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _validate(session, *, name: str, sql_expr: str, source_table: str, grain: str, exclude_id: int | None = None) -> None:
    if not name or len(name) > 128:
        raise HTTPException(status_code=422, detail="指标名不能为空且不超过 128 字")
    if not sql_expr:
        raise HTTPException(status_code=422, detail="指标表达式不能为空")
    if grain not in _GRAINS:
        raise HTTPException(status_code=422, detail="粒度仅限 daily/monthly/yearly/none")
    q = session.query(Metric).filter(Metric.name == name)
    if exclude_id is not None:
        q = q.filter(Metric.id != exclude_id)
    if q.first():
        raise HTTPException(status_code=409, detail=f"指标名已存在: {name}")
    if not session.query(MetaTable).filter(func.lower(MetaTable.name) == source_table.lower()).first():
        raise HTTPException(status_code=422, detail=f"所属表不在已同步的元数据中: {source_table}")


class MetricCreate(BaseModel):
    name: str
    aliases: list[str] = []
    sql_expr: str
    source_table: str
    default_filters: list[str] = []
    grain: str = "daily"
    comment: str = ""


class MetricUpdate(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    sql_expr: str | None = None
    source_table: str | None = None
    default_filters: list[str] | None = None
    grain: str | None = None
    comment: str | None = None


def _get(session, metric_id: int) -> Metric:
    m = session.query(Metric).filter(Metric.id == metric_id).first()
    if not m:
        raise HTTPException(status_code=404, detail=f"指标不存在: {metric_id}")
    return m


def _dump(m: Metric) -> dict:
    return {
        "id": m.id, "name": m.name, "aliases": m.aliases or [], "sql_expr": m.sql_expr,
        "source_table": m.source_table, "default_filters": m.default_filters or [],
        "grain": m.grain, "comment": m.comment,
    }


@router.get("")
async def list_metrics():
    session = new_session()
    try:
        return [_dump(m) for m in session.query(Metric).order_by(Metric.name).all()]
    finally:
        session.close()


@router.post("")
async def create_metric(body: MetricCreate):
    name = body.name.strip()
    sql_expr = body.sql_expr.strip()
    source_table = body.source_table.strip()
    session = new_session()
    try:
        _validate(session, name=name, sql_expr=sql_expr, source_table=source_table, grain=body.grain)
        m = Metric(
            name=name, aliases=_clean_list(body.aliases), sql_expr=sql_expr,
            source_table=source_table, default_filters=_clean_list(body.default_filters),
            grain=body.grain, comment=body.comment.strip(),
        )
        session.add(m)
        session.commit()
        return _dump(m)
    finally:
        session.close()


@router.put("/{metric_id}")
async def update_metric(metric_id: int, body: MetricUpdate):
    session = new_session()
    try:
        m = _get(session, metric_id)
        name = body.name.strip() if body.name is not None else m.name
        sql_expr = body.sql_expr.strip() if body.sql_expr is not None else m.sql_expr
        source_table = body.source_table.strip() if body.source_table is not None else m.source_table
        grain = body.grain if body.grain is not None else m.grain
        _validate(session, name=name, sql_expr=sql_expr, source_table=source_table, grain=grain, exclude_id=m.id)
        m.name, m.sql_expr, m.source_table, m.grain = name, sql_expr, source_table, grain
        if body.aliases is not None:
            m.aliases = _clean_list(body.aliases)
        if body.default_filters is not None:
            m.default_filters = _clean_list(body.default_filters)
        if body.comment is not None:
            m.comment = body.comment.strip()
        session.commit()
        return _dump(m)
    finally:
        session.close()


@router.delete("/{metric_id}")
async def delete_metric(metric_id: int):
    session = new_session()
    try:
        m = _get(session, metric_id)
        session.delete(m)
        session.commit()
        return {"ok": True}
    finally:
        session.close()