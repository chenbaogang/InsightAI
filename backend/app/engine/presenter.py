
import sqlglot
from sqlglot import exp

from app.models.meta import MetaColumn, MetaTable, effective_enum, new_session

MASK_CHAR = "*"


_MAX_DEPTH = 6


def _relations(select: exp.Select) -> list[exp.Expression]:
    out: list[exp.Expression] = []
    from_ = select.args.get("from_") or select.args.get("from")
    if from_ is not None and from_.this is not None:
        out.append(from_.this)
    for join in select.args.get("joins") or []:
        if join.this is not None:
            out.append(join.this)
    return out


def _unwrap(node):
    while isinstance(node, (exp.Subquery, exp.Paren)):
        node = node.this
    return node


def _cte_maps(select, ctes: dict, depth: int) -> dict:
    with_ = select.args.get("with_") or select.args.get("with")
    if with_ is None or depth > _MAX_DEPTH:
        return ctes
    out = dict(ctes)
    for cte in with_.expressions:
        inner = _unwrap(cte.this)
        m = _trace_root(inner, out, depth + 1)
        if m:
            out[(cte.alias_or_name or "").lower()] = m
    return out


def _source_maps(select: exp.Select, ctes: dict, depth: int):
    maps: dict[str, dict] = {}
    order: list[str] = []
    for rel in _relations(select):
        if isinstance(rel, exp.Subquery):
            key = (rel.alias or "").lower()
            if not key:
                continue
            maps[key] = {"derived": _trace_root(_unwrap(rel.this), ctes, depth + 1)}
        elif isinstance(rel, exp.Table):
            name = (rel.name or "").lower()
            key = (rel.alias or name).lower()
            if not key:
                continue
            maps[key] = {"cte": ctes[name]} if name in ctes else {"base": name}
        else:
            continue
        order.append(key)
    return maps, order


def _pairs_for(col: exp.Column, maps: dict, order: list[str]) -> list[tuple[str, str]]:
    cname = (col.name or "").lower()
    qual = (col.table or "").lower()
    if qual:
        src = maps.get(qual)
        if not src:
            return []
        if "base" in src:
            return [(src["base"], cname)]
        return list(next(iter(src.values())).get(cname, []))
    for key in order:
        src = maps[key]
        if "base" in src:
            continue
        pairs = next(iter(src.values())).get(cname)
        if pairs:
            return list(pairs)
    for key in order:
        if "base" in maps[key]:
            return [(maps[key]["base"], cname)]
    return []


def _merge(out: dict, name: str, pairs: list[tuple[str, str]]) -> None:
    bucket = out.setdefault(name, [])
    for p in pairs:
        if p not in bucket:
            bucket.append(p)


def _trace_select(select: exp.Select, ctes: dict, depth: int) -> dict[str, list[tuple[str, str]]]:
    if depth > _MAX_DEPTH:
        return {}
    ctes = _cte_maps(select, ctes, depth)
    maps, order = _source_maps(select, ctes, depth)
    out: dict[str, list[tuple[str, str]]] = {}
    for e in select.expressions:
        inner = e.this if isinstance(e, exp.Alias) else e
        if isinstance(inner, exp.Star) or (isinstance(inner, exp.Column) and (inner.name or "").lower() == "*"):
            qual = (inner.table or "").lower() if isinstance(inner, exp.Column) else ""
            keys = [qual] if qual else order if len(order) == 1 else []
            for key in keys:
                src = maps.get(key) or {}
                derived = src.get("cte") or (src.get("derived") if "derived" in src else None)
                for name, pairs in (derived or {}).items():
                    _merge(out, name, pairs)
            continue
        name = (e.alias_or_name or "").lower()
        if not name:
            continue
        out[name] = _pairs_for(inner, maps, order) if isinstance(inner, exp.Column) else []
    return out


def _trace_root(node, ctes: dict, depth: int) -> dict[str, list[tuple[str, str]]]:
    node = _unwrap(node)
    if node is None or depth > _MAX_DEPTH:
        return {}
    if isinstance(node, exp.Union):
        ctes = _cte_maps(node, ctes, depth)
        left = _trace_root(node.this, ctes, depth + 1)
        right = _trace_root(node.expression, ctes, depth + 1)
        out = {k: list(v) for k, v in left.items()}
        lnames = list(left)
        for i, rname in enumerate(right):
            _merge(out, lnames[i] if i < len(lnames) else rname, right[rname])
        return out
    if isinstance(node, exp.Select):
        return _trace_select(node, ctes, depth)
    select = node.find(exp.Select)
    return _trace_select(select, ctes, depth) if select is not None else {}


def trace_columns(sql: str, dialect: str) -> dict[str, list[tuple[str, str]]]:
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return {}
    return _trace_root(tree, {}, 0)


def _column_index(column_names: set[str]) -> dict[str, list[tuple[str, dict]]]:
    if not column_names:
        return {}
    session = new_session()
    try:
        rows = (
            session.query(MetaColumn, MetaTable.name)
            .join(MetaTable, MetaColumn.table_id == MetaTable.id)
            .filter(MetaColumn.name.in_(column_names))
            .all()
        )
        index: dict[str, list[tuple[str, dict]]] = {}
        for col, table_name in rows:
            index.setdefault(col.name.lower(), []).append(
                (table_name.lower(), {"enum_dict": effective_enum(col), "is_sensitive": bool(col.is_sensitive)})
            )
        return index
    finally:
        session.close()


def _pick(index: dict[str, list[tuple[str, dict]]], table: str, column: str) -> dict | None:
    hits = index.get(column)
    if not hits:
        return None
    for tname, meta in hits:
        if tname == table:
            return meta
    for _tname, meta in hits:
        return meta
    return None


def mask_value(v) -> str:
    if v is None:
        return None
    s = str(v)
    n = len(s)
    if n <= 4:
        return MASK_CHAR * max(1, n)
    head, tail = (n + 3) // 4, n // 4
    if head + tail >= n:
        return MASK_CHAR * n
    return s[:head] + MASK_CHAR * (n - head - tail) + (s[n - tail:] if tail else "")


def decode_value(v, enum_dict: dict) -> object:
    if v is None or not enum_dict:
        return v
    key = str(v).strip()
    if key in enum_dict and enum_dict[key]:
        return enum_dict[key]
    if key.endswith(".0"):
        alt = key[:-2]
        if alt in enum_dict and enum_dict[alt]:
            return enum_dict[alt]
    return v


def present(guarded_sql: str, dialect: str, columns: list[str], rows: list[list], *, admin: bool) -> dict:
    trace = trace_columns(guarded_sql, dialect)
    low = [c.lower() for c in columns]
    src_columns = {c for pairs in trace.values() for (_t, c) in pairs}
    src_columns |= {c for c in low if c not in trace}
    index = _column_index(src_columns)

    mask_at: list[int] = []
    decode_at: dict[int, dict] = {}
    for i, lname in enumerate(low):
        pairs = trace[lname] if lname in trace else [("", lname)]
        for table, column in pairs:
            meta = _pick(index, table, column)
            if not meta:
                continue
            if meta["is_sensitive"] and not admin and i not in mask_at:
                mask_at.append(i)
            if meta["enum_dict"] and i not in decode_at:
                decode_at[i] = meta["enum_dict"]

    if not mask_at and not decode_at:
        return {"columns": columns, "rows": rows, "masked_columns": [], "decoded_columns": []}

    new_rows = []
    for row in rows:
        r = list(row)
        for i in mask_at:
            r[i] = mask_value(r[i])
        for i, enum_dict in decode_at.items():
            r[i] = decode_value(r[i], enum_dict)
        new_rows.append(r)
    return {
        "columns": columns,
        "rows": new_rows,
        "masked_columns": [columns[i] for i in mask_at],
        "decoded_columns": [columns[i] for i in sorted(decode_at)],
    }

