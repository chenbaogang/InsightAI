from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_identity
from app.engine import memory, sessions
from app.engine.pipeline import UserCtx, ask
from app.models.meta import ChatTurn, new_session

router = APIRouter(prefix="/api")


class ChatReq(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str = "default"


class SessionReq(BaseModel):
    title: str = Field(default="", max_length=60)


class TitleReq(BaseModel):
    title: str = Field(min_length=1, max_length=60)


@router.post("/chat")
async def chat(req: ChatReq, bg: BackgroundTasks, user: UserCtx = Depends(current_identity)):
    holder = sessions.owner(req.session_id)
    if holder is not None and holder != user.user_id:
        raise HTTPException(status_code=403, detail="会话不属于当前账号")
    result = await ask(req.question, user, req.session_id)
    bg.add_task(memory.refresh, req.session_id)
    return result


@router.get("/sessions")
async def list_sessions(user: UserCtx = Depends(current_identity)):
    return sessions.list_for(user.user_id)


@router.post("/sessions")
async def new_session_of(req: SessionReq, user: UserCtx = Depends(current_identity)):
    return {"id": sessions.create(user.user_id, req.title)}


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, req: TitleReq, user: UserCtx = Depends(current_identity)):
    if not sessions.rename(session_id, user.user_id, req.title):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: UserCtx = Depends(current_identity)):
    if not sessions.soft_delete(session_id, user.user_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.get("/history/{session_id}")
async def history(session_id: str, user: UserCtx = Depends(current_identity)):
    session = new_session()
    try:
        turns = (
            session.query(ChatTurn)
            .filter(ChatTurn.session_id == session_id, ChatTurn.user_id == user.user_id)
            .order_by(ChatTurn.id)
            .all()
        )
        return [
            {
                "question": t.question,
                "rewritten": t.rewritten,
                "created_at": t.created_at.isoformat(),
                **(t.payload or {}),
            }
            for t in turns
        ]
    finally:
        session.close()


@router.get("/healthz")
async def healthz():
    return {"ok": True}
