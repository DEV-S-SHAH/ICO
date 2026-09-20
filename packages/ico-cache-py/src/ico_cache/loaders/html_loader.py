from typing import List
from bs4 import BeautifulSoup
from .base import BaseLoader, Chunk


class HTMLLoader(BaseLoader):
    def load(self, file_path: str) -> List[Chunk]:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        # Strip nav, boilerplate, scripts, styles
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()

        # Try to find structural elements or just get text
        blocks = soup.find_all(["p", "div", "article", "section", "h1", "h2", "h3", "h4", "h5", "h6"])

        if not blocks:
            text = soup.get_text(separator="\n\n").strip()
            if not text:
                return []
            return [
                Chunk(
                    text=text,
                    source_file=file_path,
                    page_or_section="Body",
                    chunk_index=0,
                )
            ]

        chunks = []
        chunk_idx = 0
        current_section = "Document"

        for block in blocks:
            if block.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                current_section = block.get_text(strip=True)
            else:
                text = block.get_text(strip=True)
                if text and len(text) > 20:
                    chunks.append(
                        Chunk(
                            text=text,
                            source_file=file_path,
                            page_or_section=current_section,
                            chunk_index=chunk_idx,
                        )
                    )
                    chunk_idx += 1

        return chunks

    def parse(self, file_path: str) -> List[Chunk]:
        return self.load(file_path)
