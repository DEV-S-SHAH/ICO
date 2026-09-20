import logging
import re
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.txt_loader")


class TXTLoader(BaseLoader):
    def __init__(self, schema: Optional[MetadataSchema] = None):
        self.schema = schema

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            return []

        if not content.strip():
            return []

        paragraphs = re.split(r"\n\s*\n", content)

        chunks = []
        chunk_idx = 0
        for i, p in enumerate(paragraphs):
            p = p.strip()
            if p:
                meta = {"source_file": file_path}
                if effective_schema:
                    extracted = effective_schema.extract(p)
                    meta.update({k: v for k, v in extracted.items() if v is not None})
                chunks.append(
                    Chunk(
                        text=p,
                        source_file=file_path,
                        page_or_section=f"Paragraph {i+1}",
                        chunk_index=chunk_idx,
                        metadata=meta,
                    )
                )
                chunk_idx += 1
        return chunks

    def parse(self, file_path: str) -> List[Chunk]:
        return self.load(file_path)
