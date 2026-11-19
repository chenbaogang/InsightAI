import json

import lancedb
from rank_bm25 import BM25Okapi

from app.rag.base import VecHit, VecItem
from app.rag.embeddings import tokenize

TABLE = "vecs"


def _match_filters(meta: dict, filters: dict | None) -> bool:
    if not filters:
        return True
    return all(meta.get(k) == v for k, v in filters.items())


class DimensionMismatch(RuntimeError):
    pass


class LanceStore:

    def __init__(self, path: str) -> None:
        self.db = lancedb.connect(path)
        self._bm25_cache: dict[str, tuple[list[dict], BM25Okapi]] = {}

    def index_dim(self) -> int:
        tbl = self._tbl()
        if tbl is None:
            return 0
        try:
            return int(tbl.schema.field("vector").type.list_size)
        except Exception:
            return 0

    def _check_dim(self, dim: int, op: str) -> None:
        cur = self.index_dim()
        if cur and dim and cur != dim:
            raise DimensionMismatch(
                f"向量索引维度 {cur} 与当前 embedder 维度 {dim} 不一致，无法{op}。"
                f"换 embedding_provider 后请重建索引：python scripts/reindex_vectors.py --drop"
            )

    def _tbl(self, create_data=None):
        try:
            return self.db.open_table(TABLE)
        except Exception:
            if create_data is None:
                return None
            return self.db.create_table(TABLE, data=create_data, exist_ok=True)

    def upsert(self, items: list[VecItem]) -> None:
        data = [
            {
                "id": i.id,
                "ns": i.ns,
                "text": i.text,
                "metadata": json.dumps(i.metadata, ensure_ascii=False),
                "vector": [float(x) for x in i.vector],
            }
            for i in items
        ]
        if not data:
            return
        self._check_dim(len(data[0]["vector"]), "写入")
        try:
            tbl = self.db.open_table(TABLE)
        except Exception:
            self.db.create_table(TABLE, data=data, exist_ok=True)
            self._bm25_cache.clear()
            return
        try:
            (
                tbl.merge_insert("id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(data)
            )
        except AttributeError:
            ids = ",".join("'" + i["id"].replace("'", "''") + "'" for i in data)
            tbl.delete(f"id IN ({ids})")
            tbl.add(data)
        self._bm25_cache.clear()

    def _rows(self) -> list[dict]:
        tbl = self._tbl()
        if tbl is None:
            return []
        try:
            return tbl.to_pandas().to_dict("records")
        except Exception:
            return tbl.search().limit(100_000).to_list()

    def drop_index(self) -> None:
        try:
            self.db.drop_table(TABLE)
        except Exception:
            pass
        self._bm25_cache.clear()

    def vector_search(self, ns: str, qvec: list[float], k: int, filters=None) -> list[VecHit]:
        tbl = self._tbl()
        if tbl is None:
            return []
        self._check_dim(len(qvec), "检索")
        out = []
        for r in tbl.search(qvec).where(f"ns = '{ns}'").limit(k * 3).to_list():
            if r["ns"] != ns:
                continue
            meta = json.loads(r["metadata"])
            if not _match_filters(meta, filters):
                continue
            out.append(VecHit(r["id"], ns, 1.0 / (1.0 + float(r.get("_distance", 1.0))), r["text"], meta))
            if len(out) >= k:
                break
        return out

    def bm25_search(self, ns: str, query_text: str, k: int, filters=None) -> list[VecHit]:
        if ns not in self._bm25_cache:
            rows = [r for r in self._rows() if r["ns"] == ns]
            corpus, docs = [], []
            for r in rows:
                corpus.append(tokenize(r["text"]))
                docs.append({"id": r["id"], "text": r["text"], "metadata": json.loads(r["metadata"])})
            self._bm25_cache[ns] = (docs, BM25Okapi(corpus) if corpus else None)
        docs, index = self._bm25_cache[ns]
        if index is None:
            return []
        scores = index.get_scores(tokenize(query_text))
        order = sorted(range(len(docs)), key=lambda i: -scores[i])[:k]
        hits = []
        for i in order:
            d = docs[i]
            if scores[i] <= 0 or not _match_filters(d["metadata"], filters):
                continue
            hits.append(VecHit(d["id"], ns, float(scores[i]), d["text"], d["metadata"]))
        return hits

    def hybrid_search(self, ns: str, query_text: str, query_vec: list[float], k: int, filters=None) -> list[VecHit]:
        vec = self.vector_search(ns, query_vec, k * 3, filters)
        txt = self.bm25_search(ns, query_text, k * 3, filters)
        fused: dict[str, float] = {}
        by_id: dict[str, VecHit] = {}
        for rank, h in enumerate(vec + []):
            fused[h.id] = fused.get(h.id, 0.0) + 1.0 / (60 + rank + 1)
            by_id[h.id] = h
        for rank, h in enumerate(txt):
            fused[h.id] = fused.get(h.id, 0.0) + 1.0 / (60 + rank + 1)
            by_id.setdefault(h.id, h)
        ordered = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        result = []
        for hid, score in ordered:
            h = by_id[hid]
            h.score = score
            result.append(h)
        return result


def get_vector_store():
    from app.config import get_settings

    return LanceStore(get_settings().lance_dir)

