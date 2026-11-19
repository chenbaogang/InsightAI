import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.code_dict import router as code_dict_router
from app.api.meta import router as meta_router
from app.api.metric import router as metric_router
from app.api.rbac import router as rbac_router
from app.auth.service import ensure_user_columns
from app.config import get_settings
from app.engine import schema_link
from app.models.meta import ensure_meta_columns, init_db, new_session
from app.models.rbac import Department, Role, User
from app.rbac.service import seed_defaults

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("insightai")

app = FastAPI(title="InsightAI ChatBI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(code_dict_router)
app.include_router(meta_router)
app.include_router(metric_router)
app.include_router(rbac_router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    ensure_meta_columns()
    ensure_user_columns()
    session = new_session()
    try:
        info = seed_defaults(session, get_settings().admin_init_password or None)
    finally:
        session.close()
    if info.get("created_admin"):
        logger.warning("初始管理员已就绪，请通过 /api/auth/login 登录后修改口令")
    threading.Thread(target=schema_link.warmup, name="embed-warmup", daemon=True).start()

