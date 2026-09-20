import logging
import os
import re
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.txt_loader")


class TXTLoader(BaseLoader):
    def __init__(
        self,
        schema: Optional[MetadataSchema] = None,
        max_chunk_chars: int = 2000,
    ):
        self.schema = schema
        self.max_chunk_chars = max_chunk_chars

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return []

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            return []

        if not content.strip():
            return []

        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        if not raw_paragraphs:
            return []

        chunks = []
        chunk_idx = 0

        # For small files (<= 100 paragraphs), preserve 1:1 paragraph chunks
        if len(raw_paragraphs) <= 100:
            for i, p in enumerate(raw_paragraphs):
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
        else:
            # For large files (> 100 paragraphs), coalesce consecutive paragraphs up to max_chunk_chars
            current_group: List[str] = []
            current_len = 0
            start_p = 1

            for i, p in enumerate(raw_paragraphs, start=1):
                p_len = len(p)
                if current_group and (current_len + p_len > self.max_chunk_chars):
                    coalesced_text = "\n\n".join(current_group)
                    meta = {
                        "source_file": file_path,
                        "start_paragraph": str(start_p),
                        "end_paragraph": str(i - 1),
                    }
                    if effective_schema:
                        extracted = effective_schema.extract(coalesced_text)
                        meta.update({k: v for k, v in extracted.items() if v is not None})
                    chunks.append(
                        Chunk(
                            text=coalesced_text,
                            source_file=file_path,
                            page_or_section=f"Paragraphs {start_p}-{i-1}",
                            chunk_index=chunk_idx,
                            metadata=meta,
                        )
                    )
                    chunk_idx += 1
                    current_group = [p]
                    current_len = p_len
                    start_p = i
                else:
                    current_group.append(p)
                    current_len += p_len + 2

            if current_group:
                coalesced_text = "\n\n".join(current_group)
                meta = {
                    "source_file": file_path,
                    "start_paragraph": str(start_p),
                    "end_paragraph": str(len(raw_paragraphs)),
                }
                if effective_schema:
                    extracted = effective_schema.extract(coalesced_text)
                    meta.update({k: v for k, v in extracted.items() if v is not None})
                chunks.append(
                    Chunk(
                        text=coalesced_text,
                        source_file=file_path,
                        page_or_section=f"Paragraphs {start_p}-{len(raw_paragraphs)}",
                        chunk_index=chunk_idx,
                        metadata=meta,
                    )
                )

        return chunks

    def parse(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(file_path, schema=schema)
