
import re

import sqlglot
from sqlglot import exp


class GuardError(Exception):
    pass


FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Merge, exp.Command, exp.Transaction, exp.Commit, exp.Rollback,
    exp.Grant, exp.Set,
)

SYSTEM_SCHEMA_PREFIXES = ("information_schema", "mysql", "pg_", "sys", "performance_schema", "dual")

_DEPT_VALUE_RE = re.compile(r"^[\w\u4e00-\u9fff\- ]{1,64}$")

READABLE_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def _check_readonly(tree: exp.Expression) -> None:
    for node_type in FORBIDDEN:
        if tree.find(node_type):
            raise GuardError(f"检测到禁止操作: {node_type.__name__}")
    for t in tree.find_all(exp.Table):
        schema = (t.db or "").lower()
        if schema.startswith(SYSTEM_SCHEMA_PREFIXES):
            raise GuardError(f"禁止访问系统表: {t.sql()}")


def _apply_dept_filter(tree: exp.Expression, dept_map: dict[str, str], dept_value: str | list[str]) -> None:
    values = dept_value if isinstance(dept_value, list) else [dept_value]
    for select in tree.find_all(exp.Select):
        sources = []
        from_ = select.args.get("from_") or select.args.get("from")
        if from_ is not None:
            sources.extend(from_.find_all(exp.Table))
        for join in select.args.get("joins") or []:
            sources.extend(join.find_all(exp.Table))
        for t in sources:
            col = dept_map.get(t.name.lower())
            if not col:
                continue
            alias = t.alias or t.name
            target = exp.column(col, table=alias)
            if len(values) == 1:
                cond = exp.EQ(this=target, expression=exp.Literal.string(values[0]))
            else:
                cond = exp.In(this=target, expressions=[exp.Literal.string(v) for v in values])
            select.where(cond, append=True, copy=False)


def _enforce_limit(tree: exp.Expression, row_limit: int) -> None:
    existing = tree.args.get("limit")
    if existing is not None:
        literals = [lit.name for lit in existing.find_all(exp.Literal)]
        for name in literals:
            try:
                if int(name) <= row_limit:
                    return
            except ValueError:
                break
    limit_node = exp.Limit(expression=exp.Literal.number(row_limit))
    tree.set("limit", limit_node)


def guard(
    sql: str,
    *,
    dialect: str,
    dept_map: dict[str, str],
    dept_value: str | list[str] | None,
    row_limit: int = 1000,
    admin: bool = False,
) -> str:
    statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    if len(statements) != 1:
        raise GuardError(f"禁止多语句执行（本次解析出 {len(statements)} 条）")
    tree = statements[0]

    if isinstance(tree, exp.With):
        tree = tree.this
    if not isinstance(tree, READABLE_ROOTS):
        raise GuardError(f"仅允许 SELECT 查询，收到: {type(tree).__name__}")

    _check_readonly(tree)

    if not admin and dept_value is not None:
        values = dept_value if isinstance(dept_value, list) else [dept_value]
        if not values or len(values) > 50:
            raise GuardError(f"部门取值数量非法: {len(values)}")
        for v in values:
            if not _DEPT_VALUE_RE.match(v):
                raise GuardError(f"部门标识非法: {v!r}")
        _apply_dept_filter(tree, dept_map, values)

    _enforce_limit(tree, row_limit)

    guarded = tree.sql(dialect=dialect)
    sqlglot.parse_one(guarded, read=dialect)
    return guarded

