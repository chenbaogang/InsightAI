import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.models.meta import MetaColumn, MetaTable, new_session
from app.rag.base import VecItem
from app.rag.embeddings import get_embedder
from app.rag.lance_store import get_vector_store


def build_items(embedder, session) -> list[VecItem]:
    texts: list[str] = []
    ids: list[tuple[str, str, dict]] = []

    def add(vid: str, ns: str, text: str, meta: dict) -> None:
        texts.append(text)
        ids.append((vid, ns, meta))

    for t in session.query(MetaTable).all():
        col_lines = "; ".join(f"{c.name}({c.comment})" for c in t.columns if c.comment)
        add(f"tables:{t.name}", "tables", f"{t.name} {t.comment} 字段: {col_lines}",
            {"table": t.name, "domain": t.domain})
        for c in session.query(MetaColumn).filter(MetaColumn.table_id == t.id).all():
            add(f"columns:{t.name}.{c.name}", "columns", f"{t.name}.{c.name} {c.comment} {c.data_type}",
                {"table": t.name, "column": c.name})

    t0 = time.time()
    vectors = embedder.embed(texts)
    print(f"[embed] {len(texts)} texts in {time.time()-t0:.1f}s (dim={embedder.dim})")
    return [
        VecItem(id=vid, ns=ns, text=text, metadata=meta, vector=vec)
        for (vid, ns, meta), text, vec in zip(ids, texts, vectors)
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--drop", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    embedder = get_embedder()
    store = get_vector_store()
    old_dim = store.index_dim()
    print(f"[check] provider={s.embedding_provider} dim={embedder.dim} index_dim={old_dim or '空'}")
    if args.check:
        return 0

    session = new_session()
    items = build_items(embedder, session)
    session.close()

    if old_dim and old_dim != embedder.dim:
        if not args.drop:
            print(f"[abort] 索引维度 {old_dim} != 新维度 {embedder.dim}，请加 --drop 重建")
            return 2
        store.drop_index()
        print("[drop] 旧索引已删除")

    store.upsert(items)
    by_ns: dict[str, int] = {}
    for i in items:
        by_ns[i.ns] = by_ns.get(i.ns, 0) + 1
    print(f"[done] {len(items)} vectors: {by_ns}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

