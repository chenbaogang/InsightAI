
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.meta import Base


class Department(Base):
    __tablename__ = "department"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    parent_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_values: Mapped[list | None] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    dept_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role_code: Mapped[str] = mapped_column(String(64), default="user")
    pwd_hash: Mapped[str] = mapped_column(String(256), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pwd_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

