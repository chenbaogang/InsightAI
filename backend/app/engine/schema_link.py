
from dataclasses import dataclass, field
import re
import threading

from app.models.meta import MetaTable, new_session
from app.rag.embeddings import get_embedder
from app.rag.lance_store import get_vector_store

_embedder = None
_store = None
_deps_lock = threading.Lock()


def _deps():
    global _embedder, _store
    if _embedder is None or _store is None:
        with _deps_lock:
            if _embedder is None:
                _embedder = get_embedder()
            if _store is None:
                _store = get_vector_store()
    return _embedder, _store


def warmup() -> None:
    _deps()


@dataclass
class LinkResult:
    tables: list[MetaTable] = field(default_factory=list)
    column_hits: dict[str, set[str]] = field(default_factory=dict)


def link(question: str) -> LinkResult:
    embedder, store = _deps()
    qvec = embedder.embed([question])[0]
    session = new_session()

    all_names = [r[0] for r in session.query(MetaTable.name).all()]
    q_lower = question.lower()
    pinned = [
        n for n in all_names
        if re.search(r"(?<![a-z0-9_])" + re.escape(n.lower()) + r"(?![a-z0-9_])", q_lower)
    ]
    table_hits = store.hybrid_search("tables", question, qvec, 5)
    hit_names = [h.metadata.get("table") for h in table_hits if h.metadata.get("table")]
    names = list(dict.fromkeys(pinned + hit_names))
    tables = (
        session.query(MetaTable).filter(MetaTable.name.in_(names or ["__none__"])).all()
    )
    tables.sort(key=lambda t: names.index(t.name) if t.name in names else 99)
    kept = {t.name for t in tables}

    col_hits = store.hybrid_search("columns", question, qvec, 30)
    column_hits: dict[str, set[str]] = {}
    for h in col_hits:
        tn, cn = h.metadata.get("table"), h.metadata.get("column")
        if tn and cn and tn in kept:
            column_hits.setdefault(tn, set()).add(cn)

    return LinkResult(tables=list(tables), column_hits=column_hits)


def columns_of(names: list[str]) -> dict[str, list[str]]:
    session = new_session()
    try:
        tables = session.query(MetaTable).filter(MetaTable.name.in_(names or ["__none__"])).all()
        return {t.name: [c.name for c in t.columns] for t in tables}
    finally:
        session.close()

