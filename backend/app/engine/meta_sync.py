import re
import threading

import pymysql

from app.config import get_settings
from app.engine import schema_link
from app.models.meta import MetaColumn, MetaTable, new_session
from app.rag.base import VecItem

SENSITIVE_RE = re.compile(r"phone|mobile|id_card|idcard|identity|身份证|手机号|salary|薪", re.I)

_state_lock = threading.Lock()
_state: dict = {"status": "idle", "message": "", "tables": 0, "columns": 0, "vectors": 0}


def connect():
    s = get_settings()
    if not s.starrocks_host or not s.starrocks_db:
        raise RuntimeError("请先在 backend/.env 配置 STARROCKS_HOST/DB/USER/PASSWORD")
    return pymysql.connect(
        host=s.starrocks_host, port=s.starrocks_port, user=s.starrocks_user,
        password=s.starrocks_password, database=s.starrocks_db, charset="utf8mb4",
        connect_timeout=8, cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_tables(con, names: list[str] | None):
    sql = ("SELECT table_name, table_comment, table_rows FROM information_schema.tables "
           "WHERE table_schema = %s")
    args: list = [get_settings().starrocks_db]
    if names:
        sql += " AND table_name IN (" + ",".join(["%s"] * len(names)) + ")"
        args += names
    cur = con.cursor()
    cur.execute(sql + " ORDER BY table_name", args)
    return cur.fetchall()


def fetch_columns(con, table: str):
    cur = con.cursor()
    cur.execute(
        """SELECT column_name, data_type, column_comment, ordinal_position
           FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
        (get_settings().starrocks_db, table),
    )
    return cur.fetchall()


def sync(names: list[str] | None = None, max_tables: int | None = None, progress=None, prefixes: list[str] | None = None) -> dict:
    """从 StarRocks 拉取表/列元数据写入平台库并更新向量。names 为空则同步全部（受 max_tables 限制）；prefixes 非空时只同步表名匹配任一前缀的表。"""
    report = print if progress is None else progress
    con = connect()
    try:
        rows = fetch_tables(con, names)
        if names:
            found = {r["table_name"] for r in rows}
            for n in names:
                if n not in found:
                    report(f"[warn] 表不存在，跳过: {n}")
        prefs = [p.strip().lower() for p in (prefixes or []) if p.strip()]
        if prefs:
            before = len(rows)
            rows = [r for r in rows if any(r["table_name"].lower().startswith(p) for p in prefs)]
            report(f"前缀过滤（{', '.join(prefs)}）: {before} → {len(rows)} 张表")
        if max_tables is not None:
            rows = rows[:max_tables]
        return _sync_rows(con, rows, report)
    finally:
        con.close()


def _sync_rows(con, rows, report) -> dict:
    if not rows:
        report("没有符合条件的表，未做同步")
        return {"tables": 0, "columns": 0, "vectors": 0}
    session = new_session()
    embedder, store = schema_link._deps()
    items: list[VecItem] = []
    texts: list[str] = []
    n_cols = 0
    try:
        for i, t in enumerate(rows, 1):
            tname = t["table_name"]
            report(f"[{i}/{len(rows)}] {tname}")
            cols = fetch_columns(con, tname)
            existing = session.query(MetaTable).filter(MetaTable.name == tname).first()
            mt = existing or MetaTable(name=tname)
            mt.comment = mt.comment or t["table_comment"] or ""
            mt.domain = mt.domain or ("trade" if re.match(r"(dwd|ads|dws)", tname, re.I) else "raw")
            if existing:
                known = {c.name for c in mt.columns}
            else:
                known = set()
                session.add(mt)
            for c in cols:
                if c["column_name"] in known:
                    continue
                mt.columns.append(MetaColumn(
                    name=c["column_name"],
                    data_type=c["data_type"],
                    comment=c["column_comment"] or "",
                    is_sensitive=bool(SENSITIVE_RE.search((c["column_name"] + " " + (c["column_comment"] or "")))),
                ))
            n_cols += len(mt.columns)
            col_lines = "; ".join(f"{c.name}({c.comment})" for c in mt.columns if c.comment)
            table_text = f"{tname} {mt.comment} 字段: {col_lines}"
            items.append(VecItem(
                id=f"tables:{tname}", ns="tables", text=table_text,
                metadata={"table": tname, "domain": mt.domain}, vector=[],
            ))
            texts.append(table_text)
            for c in mt.columns:
                col_text = f"{tname}.{c.name} {c.comment} {c.data_type}"
                items.append(VecItem(
                    id=f"columns:{tname}.{c.name}", ns="columns", text=col_text,
                    metadata={"table": tname, "column": c.name}, vector=[],
                ))
                texts.append(col_text)
        report(f"向量化 {len(texts)} 条文本…")
        for item, vec in zip(items, embedder.embed(texts)):
            item.vector = vec
        session.commit()
        store.upsert(items)
    finally:
        session.close()
    report(f"完成: {len(rows)} 张表, {len(items)} 条向量")
    return {"tables": len(rows), "columns": n_cols, "vectors": len(items)}


def refresh_vectors(t: MetaTable, cols: list[MetaColumn] | None = None) -> None:
    """注释被手工修改后重嵌入：表向量必刷（含列注释摘要），cols 给定时同时刷这些列的向量。"""
    embedder, store = schema_link._deps()
    items: list[VecItem] = []
    texts: list[str] = []
    col_lines = "; ".join(f"{c.name}({c.comment})" for c in t.columns if c.comment)
    table_text = f"{t.name} {t.comment} 字段: {col_lines}"
    items.append(VecItem(
        id=f"tables:{t.name}", ns="tables", text=table_text,
        metadata={"table": t.name, "domain": t.domain}, vector=[],
    ))
    texts.append(table_text)
    for c in cols or []:
        col_text = f"{t.name}.{c.name} {c.comment} {c.data_type}"
        items.append(VecItem(
            id=f"columns:{t.name}.{c.name}", ns="columns", text=col_text,
            metadata={"table": t.name, "column": c.name}, vector=[],
        ))
        texts.append(col_text)
    for item, vec in zip(items, embedder.embed(texts)):
        item.vector = vec
    store.upsert(items)


def get_status() -> dict:
    with _state_lock:
        return dict(_state)


def start_async(prefixes: list[str] | None = None) -> bool:
    """后台线程执行全量同步；已有任务在跑时返回 False。"""
    with _state_lock:
        if _state["status"] == "running":
            return False
        _state.update(status="running", message="开始同步…", tables=0, columns=0, vectors=0)

    def _progress(msg: str) -> None:
        with _state_lock:
            _state["message"] = msg

    def _run() -> None:
        try:
            result = sync(progress=_progress, prefixes=prefixes)
            with _state_lock:
                _state.update(status="done", message=f"同步完成: {result['tables']} 张表, {result['vectors']} 条向量", **result)
        except Exception as e:
            with _state_lock:
                _state.update(status="error", message=f"同步失败: {e}")

    threading.Thread(target=_run, name="meta-sync", daemon=True).start()
    return True