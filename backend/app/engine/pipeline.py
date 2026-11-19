
import json
import logging
import re
import time
from typing import TypedDict

from langgraph.graph import END, StateGraph
import sqlglot
from sqlglot import exp

from app.config import get_settings
from app.engine import chart_recommend, executor, presenter, prompt_builder, schema_link, sessions
from app.engine.sql_guard import GuardError, guard
from app.llm.client import complete, extract_sql
from app.models.meta import AuditLog, ChatTurn, new_session
from app.models.metric import metrics_for_tables

logger = logging.getLogger("insightai.pipeline")

ANALYZE_SYSTEM = (
    "你是查询分析助手。根据会话历史和最新问题，只输出一个 JSON 对象（不要其他文字）："
    '{"intent": "data_query" 或 "other", "question": "自包含的独立问题"}。'
    "intent 判断：最新问题是否在请求企业数据的查询/统计/分析（data_query），"
    "还是寒暄、闲聊、写作、与数据分析无关的内容（other）。"
    "question 改写：把最新问题补全为自包含独立问题，继承历史中的时间、指标、维度等条件，"
    "只替换最新问题中变更的部分；若已完整则原样。"
    "最新问题自身已含完整指标与对象、没有指代词时保持原样，不要给它叠加历史的维度或图表类型。"
    "历史里给了上轮实际执行的 SQL 与结果列，追问（如“再按性别拆一次”“换个条件看”）时"
    "沿用其中的表、字段名和过滤口径，只改用户明确改变的部分；不要凭猜测替换字段名。"
    "只要求换一种图表或重新绘制上一轮结果的追问仍算 data_query。"
)

REFUSAL = "抱歉，我只解答与企业数据分析相关的问题。您可以试试：按单位统计学籍数量。"

_MISSING_RE = re.compile(r"^\s*(?:MISSING_FIELD|缺字段)\s*[:：]\s*(.+)", re.I | re.S)
MISSING_PREFIX = "当前数据里没有可以回答该问题的字段："

_CHITCHAT_RE = re.compile(
    r"^\s*(你好|您好|哈喽|嗨|hi|hello|hey|早上好|下午好|晚上好|谢谢|多谢|感谢|thanks|thank you"
    r"|再见|拜拜|bye|你是谁|你是什么|你会什么|能做什么|能干什么|帮助|help|讲个笑话|测试|哈哈+|呵呵+)\s*[!！。~～?？]*\s*$",
    re.I,
)

_PRESENT_RE = re.compile(
    r"^\s*(?:那|请|帮我|我们|还是|把|将|用|要|结果|数据|这些|上面|上一轮|刚才|的)*\s*"
    r"(?:画|绘制|做成|变成|改成|换成|改为|生成|显示|展示|改|换)?\s*(?:成|为)?\s*"
    r"(柱状图|柱形图|条形图|直方图|折线图|曲线图|线图|趋势图|饼图|扇形图|散点图|面积图|表格)"
    r"\s*(?:展示|显示|来看|吧|啊|呢|吗)*\s*[。！!，,]*\s*$"
)


def _presentation_followup(question: str, history: list) -> str:
    m = _PRESENT_RE.match(question.strip())
    if not m or not history:
        return ""
    base = (history[0].rewritten or history[0].question).strip()
    base = re.sub(r"，用[^，。；]{1,8}展示$", "", base)
    return f"{base[:300]}，用{m.group(1)}展示"


def _parse_analyze(out: str, question: str) -> tuple[str, str]:
    start, end = out.find("{"), out.rfind("}")
    if start == -1 or end <= start:
        return "data_query", question[:200] or question
    try:
        obj = json.loads(out[start : end + 1])
    except json.JSONDecodeError:
        return "data_query", question[:200] or question
    intent = "data_query" if str(obj.get("intent", "")).lower() == "data_query" else "other"
    rewritten = str(obj.get("question", "")).strip()
    return intent, (rewritten[:400] if rewritten else question)


async def _analyze(question: str, session_id: str, user_id: str) -> tuple[str, str]:
    summary = (sessions.get(session_id, user_id) or {}).get("summary") or ""
    session = new_session()
    try:
        history = (
            session.query(ChatTurn)
            .filter(
                ChatTurn.session_id == session_id,
                ChatTurn.user_id == user_id,
                ChatTurn.status == "ok",
            )
            .order_by(ChatTurn.id.desc())
            .limit(5)
            .all()
        )
    finally:
        session.close()
    carried = _presentation_followup(question, list(history))
    if carried:
        return "data_query", carried
    if not history and not summary:
        return "data_query", question
    lines = []
    for t in reversed(history):
        seg = f"问: {(t.rewritten or t.question)[:200]}"
        if t.sql_guarded:
            seg += f"\n上轮SQL: {t.sql_guarded[:400]}"
        cols = (t.payload or {}).get("columns") or []
        if cols:
            seg += f"\n上轮结果列: {', '.join(str(c) for c in cols[:12])}"
        lines.append(seg)
    hist_txt = ("\n".join(lines) if lines else "（更早的轮次已归档为下方口径摘要）")
    if summary:
        hist_txt = f"已归档口径摘要:\n{summary}\n\n最近对话:\n{hist_txt}"
    try:
        out = await complete(
            [
                {"role": "system", "content": ANALYZE_SYSTEM},
                {"role": "user", "content": f"历史:\n{hist_txt}\n最新问题: {question}"},
            ]
        )
        return _parse_analyze(out, question)
    except Exception:
        logger.exception("analyze failed, fallback to original")
        return "data_query", question


class UserCtx:
    def __init__(self, user_id: str, dept: str, admin: bool = False,
                 data_values: list[str] | None = None):
        self.user_id = user_id
        self.dept = dept
        self.admin = admin
        self.data_values = data_values or []

    @property
    def dept_filter(self) -> str | list[str]:
        return self.data_values or self.dept


def _dept_map() -> dict[str, str]:
    from app.models.meta import MetaTable

    session = new_session()
    try:
        return {
            t.name.lower(): t.dept_column
            for t in session.query(MetaTable).filter(MetaTable.dept_column.isnot(None)).all()
        }
    finally:
        session.close()


def _table_names(sql: str, dialect: str) -> list[str]:
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return []
    return sorted({t.name.lower() for t in tree.find_all(exp.Table) if t.name})


def _group_exprs(sql: str, dialect: str) -> list[str]:
    try:
        g = sqlglot.parse_one(sql, read=dialect).args.get("group")
    except Exception:
        return []
    return [e.sql() for e in g.expressions] if g else []


async def _generate(messages: list[dict]) -> tuple[str, str]:
    text_out = await complete(messages)
    if re.search(r"^\s*(?:REFUSE|拒答)\s*[:：]", text_out, re.I):
        return "", ""
    m = _MISSING_RE.search(text_out)
    if m:
        return "", (m.group(1).strip()[:200] or "所需字段在表结构里不存在")
    return extract_sql(text_out), ""


class GraphState(TypedDict, total=False):
    question: str
    session_id: str
    user: "UserCtx"
    result: dict
    rewritten: str
    messages: list
    dept_map: dict
    sql: str
    guarded: str
    data: dict
    retry_reason: object
    attempts: int
    route: str


async def _n_analyze(state: GraphState) -> dict:
    result = state["result"]
    question = state["question"]
    if _CHITCHAT_RE.match(question.strip()):
        result.update(status="rejected_by_intent", answer=REFUSAL)
        return {"result": result, "route": "end"}
    intent, rewritten = await _analyze(question, state["session_id"], state["user"].user_id)
    if intent != "data_query":
        result.update(status="rejected_by_intent", answer=REFUSAL, rewritten=rewritten)
        return {"result": result, "route": "end"}
    result["rewritten"] = rewritten
    return {"result": result, "rewritten": rewritten, "route": "next"}


def _n_retrieve(state: GraphState) -> dict:
    s = get_settings()
    user = state["user"]
    links = schema_link.link(state["rewritten"])
    messages = prompt_builder.build_messages(
        state["rewritten"], links, s.datasource_dialect, None if user.admin else user.dept,
        metrics=metrics_for_tables([t.name for t in links.tables]),
    )
    return {"messages": messages, "dept_map": _dept_map(), "route": "next"}


async def _n_generate(state: GraphState) -> dict:
    result = state["result"]
    sql, missing = await _generate(state["messages"])
    if missing:
        result.update(status="missing_field", answer=MISSING_PREFIX + missing)
        return {"result": result, "route": "end"}
    if not sql:
        result.update(status="rejected_by_intent", answer=REFUSAL)
        return {"result": result, "route": "end"}
    result["sql_raw"] = sql
    return {"result": result, "sql": sql, "route": "next"}


def _n_guard(state: GraphState) -> dict:
    s = get_settings()
    user = state["user"]
    result = state["result"]
    attempts = state.get("attempts", 0)
    result["attempts"] = attempts + 1
    try:
        guarded = guard(
            state["sql"],
            dialect=s.datasource_dialect,
            dept_map=state["dept_map"],
            dept_value=None if user.admin else user.dept_filter,
            row_limit=s.query_row_limit,
            admin=user.admin,
        )
    except GuardError as e:
        result.update(status="blocked_by_guard", error=str(e))
        return {"result": result, "route": "end"}
    except Exception as e:
        result["error"] = f"SQL 解析失败: {str(e)[:200]}"
        return {"result": result, "retry_reason": e, "route": "correct"}
    result["sql_guarded"] = guarded
    return {"result": result, "guarded": guarded, "route": "next"}


async def _n_execute(state: GraphState) -> dict:
    result = state["result"]
    try:
        data = await executor.execute_readonly(state["guarded"])
    except Exception as e:
        result["error"] = str(e)[:300]
        return {"result": result, "retry_reason": e, "route": "correct"}
    return {"result": result, "data": data, "route": "next"}


async def _n_correct(state: GraphState) -> dict:
    s = get_settings()
    result = state["result"]
    retries_done = state.get("attempts", 0) + 1
    if retries_done > s.self_correct_retries:
        result["status"] = "exec_error"
        return {"result": result, "route": "end"}
    try:
        messages = prompt_builder.build_correction_messages(
            state["messages"],
            state["sql"],
            state["retry_reason"],
            schema_link.columns_of(_table_names(state["sql"], s.datasource_dialect)),
        )
        sql, missing = await _generate(messages)
    except Exception as e2:
        result["error"] = str(e2)[:300]
        result["status"] = "exec_error"
        return {"result": result, "route": "end"}
    if missing:
        result.update(status="missing_field", answer=MISSING_PREFIX + missing)
        return {"result": result, "route": "end"}
    if sql and _group_exprs(state["sql"], s.datasource_dialect) and not _group_exprs(sql, s.datasource_dialect):
        result.update(
            status="missing_field",
            answer=MISSING_PREFIX + "问题要求的分组维度在相关表里没有对应列，不允许改成不分组的统计口径",
        )
        return {"result": result, "route": "end"}
    if not sql:
        result.update(status="rejected_by_intent", answer=REFUSAL)
        return {"result": result, "route": "end"}
    return {"result": result, "messages": messages, "sql": sql, "attempts": retries_done, "route": "guard"}


def _n_chart(state: GraphState) -> dict:
    result = state["result"]
    data = state["data"]
    chart = chart_recommend.recommend(
        state["rewritten"], state["guarded"], data["columns"], data["rows"]
    )
    shown = presenter.present(
        state["guarded"],
        get_settings().datasource_dialect,
        data["columns"],
        data["rows"],
        admin=state["user"].admin,
    )
    shown["truncated"] = data["truncated"]
    result.update(
        columns=shown["columns"],
        rows=shown["rows"],
        masked_columns=shown["masked_columns"],
        decoded_columns=shown["decoded_columns"],
        truncated=data["truncated"],
        chart=chart,
        answer=_summarize(shown, chart),
    )
    return {"result": result}


_graph = None


def get_graph():
    global _graph
    if _graph is not None:
        return _graph

    g = StateGraph(GraphState)
    g.add_node("analyze", _n_analyze)
    g.add_node("retrieve", _n_retrieve)
    g.add_node("generate", _n_generate)
    g.add_node("guard", _n_guard)
    g.add_node("execute", _n_execute)
    g.add_node("correct", _n_correct)
    g.add_node("chart", _n_chart)

    g.set_entry_point("analyze")

    g.add_conditional_edges("analyze", lambda s: s.get("route"), {"end": END, "next": "retrieve"})
    g.add_edge("retrieve", "generate")
    g.add_conditional_edges("generate", lambda s: s.get("route"), {"end": END, "next": "guard"})
    g.add_conditional_edges(
        "guard", lambda s: s.get("route"), {"end": END, "next": "execute", "correct": "correct"}
    )
    g.add_conditional_edges(
        "execute", lambda s: s.get("route"), {"end": END, "next": "chart", "correct": "correct"}
    )
    g.add_conditional_edges("correct", lambda s: s.get("route"), {"end": END, "guard": "guard"})
    g.add_edge("chart", END)

    _graph = g.compile()
    return _graph


async def ask(question: str, user: UserCtx, session_id: str = "default") -> dict:
    t0 = time.monotonic()
    result: dict = {"question": question, "status": "ok", "attempts": 0, "session_id": session_id}
    state: GraphState = {
        "question": question,
        "session_id": session_id,
        "user": user,
        "result": result,
        "attempts": 0,
        "route": "next",
    }
    try:
        final = await get_graph().ainvoke(state, config={"recursion_limit": 25})
        result = final.get("result", result)
        return result
    except Exception as e:
        logger.exception("pipeline unexpected error")
        result.update(status="engine_error", error=repr(e)[:300])
        return result
    finally:
        _audit(question, user, result, int((time.monotonic() - t0) * 1000))
        _save_turn(session_id, user, result)
        try:
            sessions.touch(session_id, user.user_id, question)
        except Exception:
            logger.exception("session touch failed")


def _save_turn(session_id: str, user: UserCtx, result: dict) -> None:
    if result.get("status") != "ok":
        return
    try:
        session = new_session()
        session.add(
            ChatTurn(
                session_id=session_id,
                user_id=user.user_id,
                question=result.get("question", ""),
                rewritten=result.get("rewritten", ""),
                sql_guarded=result.get("sql_guarded", ""),
                status="ok",
                payload={
                    "columns": result.get("columns", []),
                    "rows": result.get("rows", [])[:200],
                    "chart": result.get("chart"),
                    "answer": result.get("answer", ""),
                    "sql_raw": result.get("sql_raw", ""),
                    "truncated": result.get("truncated", False),
                    "masked_columns": result.get("masked_columns", []),
                    "decoded_columns": result.get("decoded_columns", []),
                },
            )
        )
        session.commit()
        session.close()
    except Exception:
        logger.exception("turn save failed")


def _summarize(data: dict, chart: dict) -> str:
    n = len(data["rows"])
    if n == 0:
        return "查询完成，但没有符合条件的数据（可能受部门权限限制）。"
    head = f"共 {n} 行" + ("（已截断至上限）" if data["truncated"] else "")
    if chart["type"] == "kpi" and data["rows"]:
        return columns_headline(data)
    return f"{head}，已生成{chart_recommend.TYPE_NAMES.get(chart['type'], chart['type'])}。"


def columns_headline(data: dict) -> str:
    c, r = data["columns"][0], data["rows"][0][0]
    return f"{c}={r}"


def _audit(question: str, user: UserCtx, result: dict, elapsed_ms: int) -> None:
    try:
        session = new_session()
        session.add(
            AuditLog(
                user_id=user.user_id,
                dept=user.dept,
                question=question,
                sql_raw=result.get("sql_raw", ""),
                sql_guarded=result.get("sql_guarded", ""),
                status=result.get("status", "unknown"),
                rows=len(result.get("rows", [])),
                elapsed_ms=elapsed_ms,
            )
        )
        session.commit()
        session.close()
    except Exception:
        logger.exception("audit write failed")

