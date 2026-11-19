from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class MetaTable(Base):
    __tablename__ = "meta_table"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(64), default="trade")
    dept_column: Mapped[str | None] = mapped_column(String(128), nullable=True)

    columns: Mapped[list["MetaColumn"]] = relationship(back_populates="table", cascade="all, delete-orphan")


class CodeDict(Base):
    __tablename__ = "code_dict"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    entries: Mapped[dict] = mapped_column(JSON, default=dict)
    comment: Mapped[str] = mapped_column(Text, default="")


class MetaColumn(Base):
    __tablename__ = "meta_column"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("meta_table.id"))
    name: Mapped[str] = mapped_column(String(128))
    data_type: Mapped[str] = mapped_column(String(64), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    enum_dict: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    code_dict_id: Mapped[int | None] = mapped_column(ForeignKey("code_dict.id"), nullable=True)

    table: Mapped[MetaTable] = relationship(back_populates="columns")
    code_dict: Mapped[CodeDict | None] = relationship()


def effective_enum(c: MetaColumn) -> dict:
    merged = dict(c.code_dict.entries) if c.code_dict else {}
    merged.update(c.enum_dict or {})
    return merged


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    dept: Mapped[str] = mapped_column(String(64), default="")
    question: Mapped[str] = mapped_column(Text)
    sql_raw: Mapped[str] = mapped_column(Text, default="")
    sql_guarded: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="ok")
    rows: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatTurn(Base):

    __tablename__ = "chat_turn"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    question: Mapped[str] = mapped_column(Text)
    rewritten: Mapped[str] = mapped_column(Text, default="")
    sql_guarded: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="ok")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatSession(Base):

    __tablename__ = "chat_session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_from_id: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, future=True)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def ensure_meta_columns() -> None:
    from sqlalchemy import inspect, text

    engine = get_engine()
    existing = {c["name"] for c in inspect(engine).get_columns("meta_column")}
    if "code_dict_id" in existing:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE meta_column ADD COLUMN code_dict_id INTEGER REFERENCES code_dict(id)"))


def new_session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), future=True)
    return _Session()

