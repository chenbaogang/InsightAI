import uuid
from datetime import datetime

from app.models.meta import ChatSession, ChatTurn, new_session

SUMMARY_MIN_TURNS = 8
SUMMARY_KEEP_TURNS = 5
TITLE_MAX = 60


def create(user_id: str, title: str = "") -> str:
    sid = str(uuid.uuid4())
    session = new_session()
    try:
        session.add(ChatSession(id=sid, user_id=user_id, title=title[:TITLE_MAX]))
        session.commit()
    finally:
        session.close()
    return sid


def touch(session_id: str, user_id: str, question: str) -> None:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        if row is not None and row.user_id and row.user_id != user_id:
            return
        if row is None:
            row = ChatSession(id=session_id, user_id=user_id, title=(question or "")[:TITLE_MAX])
            session.add(row)
        elif not row.title:
            row.title = (question or "")[:TITLE_MAX]
        row.deleted = False
        row.updated_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()


def list_for(user_id: str, limit: int = 50) -> list[dict]:
    session = new_session()
    try:
        rows = (
            session.query(ChatSession)
            .filter(ChatSession.user_id == user_id, ChatSession.deleted == False)  # noqa: E712
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            turns = (
                session.query(ChatTurn)
                .filter(ChatTurn.session_id == r.id)
                .count()
            )
            out.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "summary": r.summary or "",
                    "turns": turns,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
            )
        return out
    finally:
        session.close()


def rename(session_id: str, user_id: str, title: str) -> bool:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        if row is None or row.user_id != user_id:
            return False
        row.title = (title or "")[:TITLE_MAX]
        row.updated_at = datetime.utcnow()
        session.commit()
        return True
    finally:
        session.close()


def soft_delete(session_id: str, user_id: str) -> bool:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        if row is None or row.user_id != user_id:
            return False
        row.deleted = True
        row.updated_at = datetime.utcnow()
        session.query(ChatTurn).filter(ChatTurn.session_id == session_id).delete()
        session.commit()
        return True
    finally:
        session.close()


def owner(session_id: str) -> str | None:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        return None if row is None else row.user_id
    finally:
        session.close()


def get(session_id: str, user_id: str | None = None) -> dict | None:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        if row is None or (user_id is not None and row.user_id != user_id):
            return None
        return {
            "id": row.id,
            "title": row.title,
            "summary": row.summary or "",
            "summary_from_id": row.summary_from_id or 0,
        }
    finally:
        session.close()


def pending_summary_turns(session_id: str) -> list[ChatTurn]:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        if row is None:
            return []
        turns = (
            session.query(ChatTurn)
            .filter(ChatTurn.session_id == session_id, ChatTurn.status == "ok")
            .order_by(ChatTurn.id)
            .all()
        )
        if len(turns) < SUMMARY_MIN_TURNS:
            return []
        cut = len(turns) - SUMMARY_KEEP_TURNS
        done = row.summary_from_id or 0
        return [t for t in turns[:cut] if t.id > done]
    finally:
        session.close()


def save_summary(session_id: str, summary: str, up_to_id: int) -> None:
    session = new_session()
    try:
        row = session.get(ChatSession, session_id)
        if row is None:
            return
        row.summary = summary[:800]
        row.summary_from_id = up_to_id
        session.commit()
    finally:
        session.close()
