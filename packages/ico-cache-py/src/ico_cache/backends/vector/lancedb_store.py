import json
import logging
import re
import lancedb
from typing import Any, List, Optional
from ..base import BaseVectorStore

logger = logging.getLogger("ico_cache.backends.vector.lancedb")

# Metadata keys/filter field names are identifiers, never expressions.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _sql_str(value: Any) -> str:
    """Render a value as a single-quoted SQL string literal, escaping quotes."""
    return "'" + str(value).replace("'", "''") + "'"


class LanceDBStore(BaseVectorStore):
    def __init__(self, uri: str = "./lancedb"):
        self.db = lancedb.connect(uri)  # type: ignore[attr-defined]

    def _table_names(self) -> List[str]:
        if hasattr(self.db, "list_tables"):
            res = self.db.list_tables()
            if hasattr(res, "tables"):
                return list(res.tables)
        try:
            return list(self.db.table_names())
        except Exception:
            return []

    async def insert(self, collection: str, id: int, vector: Any, payload: dict):
        if isinstance(vector, dict):
            row = {"id": id}
            for v_k, v_v in vector.items():
                row[f"vector_{v_k}"] = v_v
            row["vector"] = vector.get("query") or list(vector.values())[0]
        else:
            row = {"id": id, "vector": vector}

        for k, v in payload.items():
            # Structured values are stored as JSON text (LanceDB rows are flat),
            # and decoded again on read. Never rely on Python repr().
            if isinstance(v, (dict, list)):
                row[k] = json.dumps(v, default=str)
            else:
                row[k] = v

        if collection not in self._table_names():
            self.db.create_table(collection, data=[row])
            self._ensure_cosine_index(collection, "vector")
        else:
            table = self.db.open_table(collection)
            table.add([row])

    def _ensure_cosine_index(self, collection: str, vec_col: str) -> None:
        """Persist a cosine index so ``_distance`` is cosine distance.

        LanceDB moved the distance metric from the search builder to index
        creation. Newer versions of ``lancedb`` expose ``.metric`` on the
        builder, so also honor it there when the runtime supports it.
        """
        try:
            table = self.db.open_table(collection)
            create_index = getattr(table, "create_index", None)
            if create_index is not None:
                create_index(metric="cosine", vector_column_name=vec_col)
        except Exception as e:
            logger.warning(f"Cosine index unavailable for {collection}: {e}")
            # Small/seed collections may reject index creation; flat search
            # remains functional and the search layer still attempts .metric.

    async def search(
        self,
        collection: str,
        vector: Any,
        query_filter: Any,
        limit: int,
        score_threshold: float,
        using: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Any]:
        if collection not in self._table_names():
            return []

        table = self.db.open_table(collection)
        schema_names = table.schema.names if hasattr(table, "schema") else []
        vec_col = f"vector_{using}" if using and f"vector_{using}" in schema_names else "vector"

        try:
            query = table.search(vector, vector_column_name=vec_col)
            metric = getattr(query, "metric", None)
            if metric is not None:
                query = metric("cosine")
            res = query.limit(limit).to_list()
        except Exception:
            try:
                res = table.search(vector).limit(limit).to_list()
            except Exception:
                res = table.search(vector).limit(limit).to_list()

        filter_tenant_id = kwargs.get("tenant_id")
        if not filter_tenant_id and query_filter is not None and hasattr(query_filter, "must"):
            for cond in (query_filter.must or []):
                if getattr(cond, "key", None) == "tenant_id" and hasattr(cond, "match") and hasattr(cond.match, "value"):
                    filter_tenant_id = cond.match.value

        class Hit:
            def __init__(self, payload, id, score=0.0):
                self.payload = payload
                self.id = id
                self.score = score

        hits = []
        for r in res:
            hid = r.pop("id", None)
            r.pop("vector", None)
            r.pop("vector_query", None)
            r.pop("vector_context", None)
            dist = r.pop("_distance", 0.0)
            similarity = 1.0 - dist
            if score_threshold > 0 and similarity < score_threshold:
                continue

            # Reconstruct dict payload
            payload_dict = {}
            for k, v in r.items():
                if k in ("meta", "answer") and isinstance(v, str):
                    try:
                        payload_dict[k] = json.loads(v)
                    except Exception:
                        payload_dict[k] = v
                else:
                    payload_dict[k] = v

            if filter_tenant_id and payload_dict.get("tenant_id") != filter_tenant_id:
                continue

            hits.append(Hit(payload=payload_dict, id=hid, score=similarity))
        return hits

    async def delete(self, collection: str, id: int):
        if collection in self._table_names():
            table = self.db.open_table(collection)
            table.delete(f"id = {id}")

    async def get_vectors(self, collection: str, ids: List[int]) -> List[Optional[List[float]]]:
        """Get vectors by IDs from a collection."""
        if collection not in self._table_names():
            return [None] * len(ids)
        table = self.db.open_table(collection)
        results = []
        for id_val in ids:
            try:
                # Query by ID
                res = table.search().where(f"id = {id_val}").limit(1).to_list()
                if res:
                    row = res[0]
                    # Get the vector (could be 'vector', 'vector_query', or 'vector_context')
                    vector = row.get("vector") or row.get("vector_query") or row.get("vector_context")
                    if vector is not None:
                        results.append(vector)
                    else:
                        results.append(None)
                else:
                    results.append(None)
            except Exception:
                results.append(None)
        return results

    def collection_exists(self, collection: str) -> bool:
        return collection in self._table_names()

    def create_collection(self, collection: str, config: Any):
        pass

    def delete_collection(self, collection: str):
        if collection in self._table_names():
            self.db.drop_table(collection)

    async def delete_matching(self, collection: str, filter_dict: Optional[dict] = None) -> int:
        if collection not in self._table_names():
            return 0
        if not filter_dict:
            self.db.drop_table(collection)
            return -1
        table = self.db.open_table(collection)
        clauses = []
        for k, v in filter_dict.items():
            # Reject keys that could break out of the identifier/JSON context.
            if not isinstance(k, str) or not _IDENT_RE.match(k):
                continue
            if not isinstance(v, (str, int, float, bool)):
                continue
            if k == "tenant_id":
                clauses.append(f"tenant_id = {_sql_str(v)}")
            else:
                # LanceDB stores meta as a JSON string; match the escaped literal.
                pattern = '%"' + str(k) + '": "' + str(v) + '"%'
                clauses.append("meta LIKE " + _sql_str(pattern))
        if not clauses:
            return 0
        where_clause = " AND ".join(clauses)
        try:
            table.delete(where_clause)
            return len(clauses)
        except Exception:
            return 0

