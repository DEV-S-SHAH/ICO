import re
from typing import List
from .base import BaseLoader, Chunk


class TXTLoader(BaseLoader):
    def load(self, file_path: str) -> List[Chunk]:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        paragraphs = re.split(r"\n\s*\n", content)

        chunks = []
        chunk_idx = 0
        for i, p in enumerate(paragraphs):
            p = p.strip()
            if p:
                chunks.append(
                    Chunk(
                        text=p,
                        source_file=file_path,
                        page_or_section=f"Paragraph {i+1}",
                        chunk_index=chunk_idx,
                    )
                )
                chunk_idx += 1
        return chunks

    def parse(self, file_path: str) -> List[Chunk]:
        return self.load(file_path)
