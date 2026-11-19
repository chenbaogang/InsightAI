
import asyncio
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engines: dict[str, object] = {}


def _engine(url: str):
    if url not in _engines:
        _engines[url] = create_engine(url, poolclass=NullPool, future=True)
    return _engines[url]


def _serialize(v):
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _run(sql: str, limit: int) -> dict:
    with _engine(get_settings().effective_datasource_url).connect() as conn:
        rp = conn.execute(text(sql))
        columns = list(rp.keys())
        raw = rp.fetchmany(limit + 1)
    truncated = len(raw) > limit
    rows = [[_serialize(v) for v in r] for r in raw[:limit]]
    return {"columns": columns, "rows": rows, "truncated": truncated}


async def execute_readonly(sql: str) -> dict:
    s = get_settings()
    return await asyncio.wait_for(
        asyncio.to_thread(_run, sql, s.query_row_limit),
        timeout=s.query_timeout,
    )

