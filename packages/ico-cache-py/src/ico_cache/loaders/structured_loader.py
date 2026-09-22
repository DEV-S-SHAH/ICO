import csv
import json
import logging
import os
import sqlite3
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.structured_loader")


class StructuredLoader(BaseLoader):
    """
    Structured data loader for CSV, JSON, JSONL, and SQLite/SQL data.
    Produces record-based chunks preserving column names and metadata.
    Never splits a CSV row or JSON record across chunks.
    """

    def __init__(
        self,
        query: Optional[str] = None,
        schema: Optional[MetadataSchema] = None,
        rows_per_chunk: Optional[int] = None,
    ):
        self.query = query
        self.schema = schema
        self.rows_per_chunk = rows_per_chunk

    def load(self, source: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        ext = os.path.splitext(source)[1].lower() if os.path.exists(source) else ""

        try:
            if ext == ".csv":
                return self._load_csv(source, effective_schema)
            elif ext in [".json", ".jsonl"]:
                return self._load_json(source, is_jsonl=(ext == ".jsonl"), schema=effective_schema)
            elif ext in [".db", ".sqlite", ".sqlite3"] or self.query:
                return self._load_sql(source, self.query, effective_schema)
            else:
                try:
                    data = json.loads(source)
                    return self._parse_json_data(data, source_file="raw_json", schema=effective_schema)
                except Exception:
                    logger.warning(f"Unsupported or malformed structured source format: {source}")
                    return []
        except Exception as e:
            logger.warning(f"Error loading structured source {source}: {e}")
            return []

    def _load_csv(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        chunks = []
        try:
            if os.path.getsize(file_path) == 0:
                return []
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = list(csv.DictReader(f))

            total_rows = len(reader)
            if total_rows == 0:
                return []

            batch_size = self.rows_per_chunk or (50 if total_rows > 100 else 1)

            if batch_size <= 1:
                for idx, row in enumerate(reader):
                    lines = [f"{k}: {v}" for k, v in row.items() if v is not None]
                    text = "\n".join(lines)
                    meta = dict(row)
                    meta["source_file"] = file_path
                    if schema:
                        extracted = schema.extract(text)
                        meta.update({k: v for k, v in extracted.items() if v is not None})
                    chunks.append(
                        Chunk(
                            text=text,
                            source_file=file_path,
                            page_or_section=f"Row {idx + 1}",
                            chunk_index=idx,
                            metadata=meta,
                        )
                    )
            else:
                chunk_idx = 0
                for start_idx in range(0, total_rows, batch_size):
                    end_idx = min(start_idx + batch_size, total_rows)
                    batch = reader[start_idx:end_idx]

                    row_blocks = []
                    for r_i, row in enumerate(batch, start=start_idx + 1):
                        lines = [f"{k}: {v}" for k, v in row.items() if v is not None]
                        row_blocks.append(f"--- Row {r_i} ---\n" + "\n".join(lines))

                    text = "\n\n".join(row_blocks)
                    meta = {
                        "source_file": file_path,
                        "start_row": start_idx + 1,
                        "end_row": end_idx,
                        "row_count": len(batch),
                    }
                    if schema:
                        extracted = schema.extract(text)
                        meta.update({k: v for k, v in extracted.items() if v is not None})

                    chunks.append(
                        Chunk(
                            text=text,
                            source_file=file_path,
                            page_or_section=f"Rows {start_idx + 1}-{end_idx}",
                            chunk_index=chunk_idx,
                            metadata=meta,
                        )
                    )
                    chunk_idx += 1
        except Exception as e:
            logger.warning(f"Failed to parse CSV file {file_path}: {e}")
            return []
        return chunks

    def _load_json(
        self, file_path: str, is_jsonl: bool = False, schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        chunks = []
        try:
            if os.path.getsize(file_path) == 0:
                return []

            if is_jsonl:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for idx, line in enumerate(f):
                        line = line.strip()
                        if line:
                            try:
                                record = json.loads(line)
                                chunks.append(self._record_to_chunk(record, file_path, idx, schema))
                            except Exception as e:
                                logger.warning(f"Skipping malformed JSON line {idx+1} in {file_path}: {e}")
            else:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                    if not content:
                        return []
                    data = json.loads(content)
                    chunks.extend(self._parse_json_data(data, source_file=file_path, schema=schema))
        except Exception as e:
            logger.warning(f"Failed to parse JSON file {file_path}: {e}")
            return []
        return chunks

    def _parse_json_data(
        self, data, source_file: str, schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        if isinstance(data, list):
            return [self._record_to_chunk(rec, source_file, idx, schema) for idx, rec in enumerate(data)]
        elif isinstance(data, dict):
            return [self._record_to_chunk(data, source_file, 0, schema)]
        return []

    def _record_to_chunk(
        self, record, source_file: str, idx: int, schema: Optional[MetadataSchema] = None
    ) -> Chunk:
        if isinstance(record, dict):
            lines = [f"{k}: {v}" for k, v in record.items()]
            text = "\n".join(lines)
            meta = {k: v for k, v in record.items() if isinstance(v, (str, int, float, bool))}
        else:
            text = str(record)
            meta = {}
        meta["source_file"] = source_file
        if schema:
            extracted = schema.extract(text)
            meta.update({k: v for k, v in extracted.items() if v is not None})
        return Chunk(
            text=text,
            source_file=source_file,
            page_or_section=f"Record {idx + 1}",
            chunk_index=idx,
            metadata=meta,
        )

    def _load_sql(
        self, db_path: str, query: Optional[str], schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        q = query or "SELECT * FROM sqlite_master WHERE type='table'"
        chunks = []
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(q)
                rows = cursor.fetchall()
                for idx, row in enumerate(rows):
                    row_dict = dict(row)
                    meta = {k: v for k, v in row_dict.items() if isinstance(v, (str, int, float, bool))}
                    meta["source_file"] = db_path
                    text = "\n".join(f"{k}: {v}" for k, v in row_dict.items())
                    if schema:
                        extracted = schema.extract(text)
                        meta.update({k: v for k, v in extracted.items() if v is not None})
                    chunks.append(
                        Chunk(
                            text=text,
                            source_file=db_path,
                            page_or_section=f"Row {idx + 1}",
                            chunk_index=idx,
                            metadata=meta,
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to query SQL database {db_path}: {e}")
            return []
        return chunks
