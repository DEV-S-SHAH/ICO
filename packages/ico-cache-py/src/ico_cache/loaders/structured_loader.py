import csv
import json
import os
import sqlite3
from typing import List, Optional
from .base import BaseLoader, Chunk


class StructuredLoader(BaseLoader):
    """
    Structured data loader for CSV, JSON, JSONL, and SQLite/SQL data.
    Produces record-based chunks preserving column names and metadata.
    """

    def __init__(self, query: Optional[str] = None):
        self.query = query

    def load(self, source: str) -> List[Chunk]:
        ext = os.path.splitext(source)[1].lower() if os.path.exists(source) else ""

        if ext == ".csv":
            return self._load_csv(source)
        elif ext in [".json", ".jsonl"]:
            return self._load_json(source, is_jsonl=(ext == ".jsonl"))
        elif ext in [".db", ".sqlite", ".sqlite3"] or self.query:
            return self._load_sql(source, self.query)
        else:
            # Try parsing as raw JSON string
            try:
                data = json.loads(source)
                return self._parse_json_data(data, source_file="raw_json")
            except Exception:
                raise ValueError(f"Unsupported structured source format: {source}")

    def _load_csv(self, file_path: str) -> List[Chunk]:
        chunks = []
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                lines = [f"{k}: {v}" for k, v in row.items() if v is not None]
                text = "\n".join(lines)
                chunks.append(
                    Chunk(
                        text=text,
                        source_file=file_path,
                        page_or_section=f"Row {idx + 1}",
                        chunk_index=idx,
                        metadata=dict(row),
                    )
                )
        return chunks

    def _load_json(self, file_path: str, is_jsonl: bool = False) -> List[Chunk]:
        chunks = []
        if is_jsonl:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        chunks.append(self._record_to_chunk(record, file_path, idx))
        else:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                chunks.extend(self._parse_json_data(data, source_file=file_path))
        return chunks

    def _parse_json_data(self, data, source_file: str) -> List[Chunk]:
        if isinstance(data, list):
            return [self._record_to_chunk(rec, source_file, idx) for idx, rec in enumerate(data)]
        elif isinstance(data, dict):
            return [self._record_to_chunk(data, source_file, 0)]
        return []

    def _record_to_chunk(self, record, source_file: str, idx: int) -> Chunk:
        if isinstance(record, dict):
            lines = [f"{k}: {v}" for k, v in record.items()]
            text = "\n".join(lines)
            meta = {k: v for k, v in record.items() if isinstance(v, (str, int, float, bool))}
        else:
            text = str(record)
            meta = {}
        return Chunk(
            text=text,
            source_file=source_file,
            page_or_section=f"Record {idx + 1}",
            chunk_index=idx,
            metadata=meta,
        )

    def _load_sql(self, db_path: str, query: Optional[str]) -> List[Chunk]:
        q = query or "SELECT * FROM sqlite_master WHERE type='table'"
        chunks = []
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(q)
            rows = cursor.fetchall()
            for idx, row in enumerate(rows):
                row_dict = dict(row)
                lines = [f"{k}: {v}" for k, v in row_dict.items()]
                chunks.append(
                    Chunk(
                        text="\n".join(lines),
                        source_file=db_path,
                        page_or_section=f"Row {idx + 1}",
                        chunk_index=idx,
                        metadata=row_dict,
                    )
                )
        return chunks
