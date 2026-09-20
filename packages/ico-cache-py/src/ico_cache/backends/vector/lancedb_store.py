import json
import lancedb
from typing import Any, List, Optional
from ..base import BaseVectorStore


class LanceDBStore(BaseVectorStore):
    def __init__(self, uri: str = "./lancedb"):
        self.db = lancedb.connect(uri)

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
            if k == "meta" and isinstance(v, dict):
                row[k] = json.dumps(v)
            else:
                row[k] = str(v) if isinstance(v, dict) else v

        if collection not in self._table_names():
            self.db.create_table(collection, data=[row])
        else:
            table = self.db.open_table(collection)
            table.add([row])

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
            res = table.search(vector, vector_column_name=vec_col).metric("cosine").limit(limit).to_list()
        except Exception:
            try:
                res = table.search(vector).metric("cosine").limit(limit).to_list()
            except Exception:
                res = table.search(vector).limit(limit).to_list()

        filter_tenant_id = kwargs.get("tenant_id")
        if not filter_tenant_id and query_filter is not None and hasattr(query_filter, "must"):
            for cond in (query_filter.must or []):
                if getattr(cond, "key", None) == "tenant_id" and hasattr(cond, "match") and hasattr(cond.match, "value"):
                    filter_tenant_id = cond.match.value

        class Hit:
            def __init__(self, payload, id):
                self.payload = payload
                self.id = id

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
                if k == "meta" and isinstance(v, str):
                    try:
                        payload_dict[k] = json.loads(v)
                    except Exception:
                        payload_dict[k] = v
                elif k == "answer" and isinstance(v, str):
                    try:
                        payload_dict[k] = json.loads(v.replace("'", '"'))
                    except Exception:
                        payload_dict[k] = v
                else:
                    payload_dict[k] = v

            if filter_tenant_id and payload_dict.get("tenant_id") != filter_tenant_id:
                continue

            hits.append(Hit(payload=payload_dict, id=hid))
        return hits

    async def delete(self, collection: str, id: int):
        if collection in self._table_names():
            table = self.db.open_table(collection)
            table.delete(f"id = {id}")

    def collection_exists(self, collection: str) -> bool:
        return collection in self._table_names()

    def create_collection(self, collection: str, config: Any):
        pass
