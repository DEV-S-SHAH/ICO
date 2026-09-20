from typing import List
import PyPDF2
from .base import BaseLoader, Chunk


class PDFLoader(BaseLoader):
    def load(self, file_path: str) -> List[Chunk]:
        chunks = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    chunks.append(
                        Chunk(
                            text=text.strip(),
                            source_file=file_path,
                            page_or_section=f"Page {i+1}",
                            chunk_index=i,
                        )
                    )
        return chunks

    def parse(self, file_path: str) -> List[Chunk]:
        return self.load(file_path)
