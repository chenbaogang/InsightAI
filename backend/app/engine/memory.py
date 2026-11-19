import logging

from app.engine import sessions
from app.llm.client import LLMError, LLMNotConfigured, complete

logger = logging.getLogger("insightai.memory")

SUMMARY_SYSTEM = (
    "你是查询口径归档助手。把给定的历史问答压缩成不超过 200 字的中文要点，"
    "只保留后续追问需要继承的口径：分析对象、涉及的表和字段、时间范围、"
    "部门或维度过滤条件、用户已确认或已纠正的口径决定。"
    "禁止输出任何统计数值、人数、金额或比例。"
    "信息不足时只输出已有的要点，不要编造。"
)


async def refresh(session_id: str) -> str:
    pending = sessions.pending_summary_turns(session_id)
    if not pending:
        return ""
    old = sessions.get(session_id) or {}
    lines = []
    for t in pending:
        seg = f"问: {(t.rewritten or t.question)[:200]}"
        if t.sql_guarded:
            seg += f"\nSQL: {t.sql_guarded[:300]}"
        lines.append(seg)
    prior = (old.get("summary") or "").strip()
    user_txt = (f"已有摘要:\n{prior}\n\n新增历史:\n" if prior else "历史:\n") + "\n".join(lines)
    try:
        out = await complete(
            [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": user_txt}]
        )
    except (LLMError, LLMNotConfigured) as e:
        logger.warning("会话摘要生成失败 session=%s: %s", session_id, str(e)[:200])
        return ""
    summary = out.strip()[:800]
    if not summary:
        return ""
    sessions.save_summary(session_id, summary, pending[-1].id)
    return summary
