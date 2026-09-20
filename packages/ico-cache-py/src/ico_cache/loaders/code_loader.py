import ast
import os
from typing import List
from .base import BaseLoader, Chunk


class CodeLoader(BaseLoader):
    """
    CodeLoader parses source code files and splits them into semantically meaningful
    AST chunks (functions, classes, and module-level blocks) preserving structural context.
    """

    def __init__(self, language: str = "python"):
        self.language = language.lower()

    def load(self, source: str) -> List[Chunk]:
        if os.path.exists(source):
            with open(source, "r", encoding="utf-8", errors="replace") as f:
                code_text = f.read()
            source_file = source
        else:
            code_text = source
            source_file = "raw_code"

        if self.language == "python" or source_file.endswith(".py"):
            return self._parse_python_ast(code_text, source_file)
        else:
            return self._parse_generic_ast(code_text, source_file)

    def _parse_python_ast(self, code_text: str, source_file: str) -> List[Chunk]:
        try:
            tree = ast.parse(code_text)
        except SyntaxError:
            return self._parse_generic_ast(code_text, source_file)

        lines = code_text.splitlines()
        chunks: List[Chunk] = []
        chunk_idx = 0

        # Module docstring chunk if present
        docstring = ast.get_docstring(tree)
        if docstring:
            chunks.append(
                Chunk(
                    text=docstring,
                    source_file=source_file,
                    page_or_section="Module Docstring",
                    chunk_index=chunk_idx,
                    metadata={"type": "module_docstring", "name": os.path.basename(source_file)},
                )
            )
            chunk_idx += 1

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                chunk_code = "\n".join(lines[start:end])
                doc = ast.get_docstring(node) or ""
                chunks.append(
                    Chunk(
                        text=chunk_code,
                        source_file=source_file,
                        page_or_section=f"Function {node.name}",
                        chunk_index=chunk_idx,
                        metadata={
                            "type": "function",
                            "name": node.name,
                            "start_line": node.lineno,
                            "end_line": end,
                            "docstring": doc,
                        },
                    )
                )
                chunk_idx += 1

            elif isinstance(node, ast.ClassDef):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                chunk_code = "\n".join(lines[start:end])
                doc = ast.get_docstring(node) or ""
                chunks.append(
                    Chunk(
                        text=chunk_code,
                        source_file=source_file,
                        page_or_section=f"Class {node.name}",
                        chunk_index=chunk_idx,
                        metadata={
                            "type": "class",
                            "name": node.name,
                            "start_line": node.lineno,
                            "end_line": end,
                            "docstring": doc,
                        },
                    )
                )
                chunk_idx += 1

        if not chunks:
            # Fallback if file has only top-level statements
            return self._parse_generic_ast(code_text, source_file)

        return chunks

    def _parse_generic_ast(self, code_text: str, source_file: str) -> List[Chunk]:
        """Line-group chunking fallback for non-python or malformed syntax."""
        lines = code_text.splitlines()
        chunks: List[Chunk] = []
        step = 50
        chunk_idx = 0
        for i in range(0, max(1, len(lines)), step):
            slice_lines = lines[i : i + step]
            if not slice_lines:
                continue
            chunks.append(
                Chunk(
                    text="\n".join(slice_lines),
                    source_file=source_file,
                    page_or_section=f"Lines {i + 1}-{i + len(slice_lines)}",
                    chunk_index=chunk_idx,
                    metadata={"start_line": i + 1, "end_line": i + len(slice_lines)},
                )
            )
            chunk_idx += 1
        return chunks
