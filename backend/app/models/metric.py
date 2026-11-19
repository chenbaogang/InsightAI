from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.meta import Base, new_session


class Metric(Base):
    __tablename__ = "metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sql_expr: Mapped[str] = mapped_column(Text)
    source_table: Mapped[str] = mapped_column(String(128))
    default_filters: Mapped[list | None] = mapped_column(JSON, nullable=True)
    grain: Mapped[str] = mapped_column(String(32), default="daily")
    comment: Mapped[str] = mapped_column(Text, default="")


def metrics_for_tables(table_names: list[str]) -> list[Metric]:
    if not table_names:
        return []
    names = {n.lower() for n in table_names}
    session = new_session()
    try:
        rows = session.query(Metric).order_by(Metric.name).all()
        return [m for m in rows if m.source_table.lower() in names]
    finally:
        session.close()