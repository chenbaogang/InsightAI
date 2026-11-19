
import re

SHARE_HINTS = re.compile(r"占比|比例|分布|构成", re.I)

_TYPE_WORDS = (
    ("pie", ("饼图", "扇形图")),
    ("line", ("折线图", "曲线图", "线图", "趋势图")),
    ("bar", ("柱状图", "柱形图", "条形图", "直方图")),
    ("table", ("表格", "列表")),
)

TYPE_NAMES = {"bar": "柱状图", "line": "折线图", "pie": "饼图", "kpi": "指标卡", "table": "表格"}


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_TIME_NAME = re.compile(r"(年|月|日|期|季度|date|time|year|month|day|_dt|_rq|_ny|xn|_qm)", re.I)


def _looks_time(values: list, name: str = "") -> bool:
    pat = re.compile(r"^(\d{4})(-\d{1,2})?(-\d{1,2})?$")
    sample = [v for v in values[:20] if v is not None]
    if not sample:
        return False

    def ok(v) -> bool:
        if hasattr(v, "isoformat"):
            return True
        if not isinstance(v, str):
            return False
        m = pat.match(v.strip())
        if not m:
            return False
        if m.group(2) is not None:
            return True
        return bool(_TIME_NAME.search(name)) and 1900 <= int(m.group(1)) <= 2100

    return sum(1 for v in sample if ok(v)) >= len(sample) * 0.8


def explicit_type(question: str) -> str:
    for t, words in _TYPE_WORDS:
        if any(w in question for w in words):
            return t
    return ""


def _indices(columns: list[str], rows: list[list]) -> tuple[int, list[int], list[int]]:
    n = len(columns)
    time_idx = next((i for i in range(n) if _looks_time([r[i] for r in rows], str(columns[i]))), -1)
    num_idx = [i for i in range(n) if _is_number(rows[0][i])]
    cat_idx = [i for i in range(n) if i != time_idx and i not in num_idx]
    return time_idx, num_idx, cat_idx


def _forced(t: str, columns: list[str], rows: list[list]) -> dict | None:
    if t == "table":
        return {"type": "table", "x": 0, "series": []}
    time_idx, num_idx, cat_idx = _indices(columns, rows)
    if not num_idx:
        return None
    if t == "pie":
        if len(num_idx) != 1 or len(cat_idx) != 1:
            return None
        return {"type": "pie", "x": cat_idx[0], "series": num_idx}
    x = time_idx if time_idx >= 0 else (cat_idx[0] if cat_idx else 0)
    series = [i for i in num_idx if i != x]
    if not series:
        return None
    return {"type": t, "x": x, "series": series}


def recommend(question: str, sql: str, columns: list[str], rows: list[list]) -> dict:
    et = explicit_type(question)
    if et and rows:
        forced = _forced(et, columns, rows)
        if forced:
            return forced
    has_agg = bool(re.search(r"\b(sum|count|avg|max|min)\s*\(", sql, re.I))
    grouped = bool(re.search(r"group by", sql, re.I))
    if not has_agg or not rows:
        return {"type": "table", "x": 0, "series": []}
    if not grouped and len(rows) != 1:
        return {"type": "table", "x": 0, "series": []}

    n = len(columns)
    time_idx, num_idx, cat_idx = _indices(columns, rows)

    if time_idx >= 0 and num_idx:
        return {"type": "line", "x": time_idx, "series": num_idx}
    if len(num_idx) == 1 and not cat_idx and len(rows) == 1:
        return {"type": "kpi", "x": 0, "series": num_idx}
    if len(cat_idx) == 1 and num_idx:
        if len(num_idx) == 1 and SHARE_HINTS.search(question):
            return {"type": "pie", "x": cat_idx[0], "series": [num_idx[0]]}
        return {"type": "bar", "x": cat_idx[0], "series": num_idx}
    if len(rows) == 1 and len(num_idx) == 1:
        return {"type": "kpi", "x": 0, "series": [num_idx[0]]}
    return {"type": "table", "x": 0, "series": []}

