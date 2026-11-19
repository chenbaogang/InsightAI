from datetime import date

import re

from app.engine.schema_link import LinkResult
from app.models.meta import effective_enum

SYSTEM_RULES = """你是企业数据分析平台的 Text-to-SQL 引擎。规则：
1. 只输出一条只读 SELECT 语句，放在 ```sql 代码块中，不要输出解释。
2. 使用 {dialect} 方言；列一律用简单英文别名。
3. 禁止 INSERT/UPDATE/DELETE/DROP 等任何写操作，禁止查询系统表。
4. 平台会自动追加部门过滤条件（{dept_note}），你无需手写部门条件，也不要查询不属于本部门的维度。
5. 结果最多 1000 行，聚合优先。
6. 列注释中的枚举写作 key=含义；WHERE 过滤必须用 key 原值，含义部分不是数据值，禁止写入 SQL。
7. 只能使用上面列出的表和列名。问题需要的维度或指标在表结构里没有对应列时，不要臆造列名，也不要拿名字相近的列替代，更不要删掉该维度只回答剩下的部分，只输出一行：MISSING_FIELD: <一句话说明缺什么>。
8. 若用户问题与上述表结构/指标完全无关（寒暄、闲聊、写作、通用常识等），不要生成 SQL，只输出一行：REFUSE: <一句话原因>。
9. 跨表 JOIN 只能用两张表里含义一致的列（如 单位号=单位号）；不得用主键唯一标识、学号、工号这类本表专有编号去 JOIN 另一类主体表。找不到这样的列就输出 MISSING_FIELD: <一句话说明缺什么>。
今天是 {today}。"""


_KEY_COL_RE = re.compile(r"(^id$|_id$)", re.I)
_WIDE_TABLE_THRESHOLD = 40
_WIDE_COL_CAP = 50


def _select_columns(t, recall: set[str]) -> list:
    cols = list(t.columns)
    if len(cols) <= _WIDE_TABLE_THRESHOLD:
        return [c for c in cols if c.comment] or cols
    dept_col = getattr(t, "dept_column", None)
    keep, kept_names = [], set()
    for c in cols:
        if c.name in recall or effective_enum(c) or _KEY_COL_RE.search(c.name) or c.name == dept_col:
            keep.append(c)
            kept_names.add(c.name)
    if len(keep) < 10:
        for c in cols:
            if c.comment and c.name not in kept_names:
                keep.append(c)
                kept_names.add(c.name)
                if len(keep) >= 10:
                    break
    return keep[:_WIDE_COL_CAP]


def _ddl_block(tables, column_hits: dict[str, set[str]] | None = None) -> str:
    hits = column_hits or {}
    lines = []
    for t in tables:
        comment = f" -- {t.comment}" if t.comment else ""
        lines.append(f"表 {t.name}{comment}")
        for c in _select_columns(t, hits.get(t.name, set())):
            extra = []
            if c.comment:
                extra.append(c.comment)
            enum = effective_enum(c)
            if enum:
                extra.append("枚举: " + ", ".join(f"{k}={v}" for k, v in enum.items()))
            suffix = f"  -- {'; '.join(extra)}" if extra else ""
            lines.append(f"  {c.name} {c.data_type}{suffix}")
    return "\n".join(lines)


def _metrics_block(metrics) -> str:
    lines = ["# 指标口径（问题涉及这些指标时必须遵循）"]
    for m in metrics:
        aliases = f"（别名: {'、'.join(m.aliases)}）" if m.aliases else ""
        lines.append(f"{m.name}{aliases} | 表 {m.source_table} | 粒度 {m.grain}")
        lines.append(f"  表达式: {m.sql_expr}")
        if m.default_filters:
            lines.append("  默认条件: " + " AND ".join(m.default_filters))
        if m.comment:
            lines.append(f"  口径: {m.comment}")
    return "\n".join(lines)


def build_messages(
    question: str, links: LinkResult, dialect: str, dept_value: str | None, metrics: list | None = None
) -> list[dict]:
    dept_note = f"部门 = '{dept_value}'" if dept_value else "管理员，无部门限制"
    system = SYSTEM_RULES.format(dialect=dialect, dept_note=dept_note, today=date.today().isoformat())
    metrics = metrics or []
    if metrics:
        system += "\n10. 问题涉及「指标口径」中的指标时，必须使用该指标的表达式和默认条件，不得自行改写口径。"

    parts = ["# 可用表结构", _ddl_block(links.tables, links.column_hits)]
    if metrics:
        parts.append(_metrics_block(metrics))
    parts.append("# 用户问题")
    parts.append(question)

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def build_correction_messages(
    prev_messages, bad_sql, db_error, table_columns: dict[str, list[str]] | None = None
) -> list[dict]:
    err = str(db_error)[:300]
    note = f"该 SQL 执行报错：{err}\n"
    if table_columns:
        listing = "\n".join(f"  {t}: {', '.join(cols)}" for t, cols in table_columns.items())
        note += f"这些表的完整可用列（只能从中选取，不得臆造）：\n{listing}\n"
        note += (
            "若问题所需的信息不在上述列中，不要换列猜测，也不要删掉问题要求的维度或过滤条件"
            "来凑一条能执行的 SQL，只输出一行：MISSING_FIELD: <一句话说明缺什么>。\n"
        )
    note += "否则请修正后重新输出，仍然只输出一条 SELECT。"
    return prev_messages + [
        {"role": "assistant", "content": f"```sql\n{bad_sql}\n```"},
        {"role": "user", "content": note},
    ]

