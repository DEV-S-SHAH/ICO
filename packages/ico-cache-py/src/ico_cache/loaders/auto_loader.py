import glob
import os
from typing import List, Optional
from .base import Chunk


def _get_parser(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        from .pdf_loader import PDFLoader

        return PDFLoader()
    elif ext in [".htm", ".html"]:
        from .html_loader import HTMLLoader

        return HTMLLoader()
    elif ext == ".txt":
        from .txt_loader import TXTLoader

        return TXTLoader()
    elif ext in [".csv", ".json", ".jsonl"]:
        from .structured_loader import StructuredLoader

        return StructuredLoader()
    elif ext in [".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp"]:
        from .code_loader import CodeLoader

        return CodeLoader()
    else:
        raise ValueError(f"Unsupported file extension: {ext}")


def ingest(
    path: Optional[str] = None,
    raw_text: Optional[str] = None,
    source_id: Optional[str] = None,
) -> List[Chunk]:
    chunks: List[Chunk] = []
    if path:
        if "*" in path:
            files = glob.glob(path)
        else:
            files = [path]

        for f in files:
            parser = _get_parser(f)
            chunks.extend(parser.load(f))

    if raw_text:
        source = source_id or "manual"
        chunks.append(
            Chunk(
                text=raw_text,
                source_file=source,
                page_or_section="Manual Input",
                chunk_index=0,
            )
        )

    return chunks
