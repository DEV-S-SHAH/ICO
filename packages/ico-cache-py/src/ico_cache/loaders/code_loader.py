import ast
import logging
import os
from typing import List, Optional
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.code_loader")


class CodeLoader(BaseLoader):
    """
    CodeLoader parses source code files and splits them into semantically meaningful
    AST chunks (functions, classes, and module-level blocks) preserving structural context.
    Never splits a function or class body across chunks.
    Supports Python (via ast), JavaScript/TypeScript, and Go (via tree-sitter).
    """

    def __init__(self, language: Optional[str] = None, schema: Optional[MetadataSchema] = None):
        self.language = language.lower() if language else None
        self.schema = schema

    def load(self, source: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        if os.path.exists(source):
            if os.path.getsize(source) == 0:
                return []
            try:
                with open(source, "r", encoding="utf-8", errors="replace") as f:
                    code_text = f.read()
            except Exception as e:
                logger.warning(f"Failed to read source file {source}: {e}")
                return []
            source_file = source
        else:
            code_text = source
            source_file = "raw_code"

        if not code_text.strip():
            return []

        ext = os.path.splitext(source_file)[1].lower()
        lang = self.language or ext.lstrip(".")

        if lang in ["py", "python"]:
            return self._parse_python_ast(code_text, source_file, effective_schema)
        elif lang in ["js", "jsx", "javascript", "ts", "tsx"]:
            return self._parse_tree_sitter_js(code_text, source_file, effective_schema)
        elif lang in ["go", "golang"]:
            return self._parse_tree_sitter_go(code_text, source_file, effective_schema)
        else:
            return self._parse_generic_ast(code_text, source_file, effective_schema)

    def _parse_python_ast(
        self, code_text: str, source_file: str, schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        try:
            tree = ast.parse(code_text)
        except (SyntaxError, Exception):
            # Gracefully fallback for malformed Python files (produces reasonably-sized line chunks)
            return self._parse_generic_ast(code_text, source_file, schema)

        lines = code_text.splitlines()
        chunks: List[Chunk] = []
        chunk_idx = 0

        # Module docstring chunk if present
        docstring = ast.get_docstring(tree)
        if docstring:
            meta = {
                "source_file": source_file,
                "type": "module_docstring",
                "name": os.path.basename(source_file),
            }
            if schema:
                extracted = schema.extract(docstring)
                meta.update({k: v for k, v in extracted.items() if v is not None})
            chunks.append(
                Chunk(
                    text=docstring,
                    source_file=source_file,
                    page_or_section="Module Docstring",
                    chunk_index=chunk_idx,
                    metadata=meta,
                )
            )
            chunk_idx += 1

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                chunk_code = "\n".join(lines[start:end])
                doc = ast.get_docstring(node) or ""
                meta = {
                    "source_file": source_file,
                    "type": "function",
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": end,
                    "docstring": doc,
                }
                if schema:
                    extracted = schema.extract(chunk_code)
                    meta.update({k: v for k, v in extracted.items() if v is not None})
                chunks.append(
                    Chunk(
                        text=chunk_code,
                        source_file=source_file,
                        page_or_section=f"Function {node.name}",
                        chunk_index=chunk_idx,
                        metadata=meta,
                    )
                )
                chunk_idx += 1

            elif isinstance(node, ast.ClassDef):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                chunk_code = "\n".join(lines[start:end])
                doc = ast.get_docstring(node) or ""
                meta = {
                    "source_file": source_file,
                    "type": "class",
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": end,
                    "docstring": doc,
                }
                if schema:
                    extracted = schema.extract(chunk_code)
                    meta.update({k: v for k, v in extracted.items() if v is not None})
                chunks.append(
                    Chunk(
                        text=chunk_code,
                        source_file=source_file,
                        page_or_section=f"Class {node.name}",
                        chunk_index=chunk_idx,
                        metadata=meta,
                    )
                )
                chunk_idx += 1

        if not chunks:
            # Fallback if file has only top-level statements
            return self._parse_generic_ast(code_text, source_file, schema)

        return chunks

    def _parse_tree_sitter_js(
        self, code_text: str, source_file: str, schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        try:
            import tree_sitter_javascript as tsjs
            from tree_sitter import Language, Parser

            js_lang = Language(tsjs.language())
            parser = Parser(js_lang)
            tree = parser.parse(code_text.encode("utf-8"))
        except Exception as e:
            logger.warning(f"Tree-sitter JS parse error on {source_file}: {e}; falling back.")
            return self._parse_generic_ast(code_text, source_file, schema)

        lines = code_text.splitlines()
        chunks: List[Chunk] = []
        chunk_idx = 0

        target_types = (
            "function_declaration",
            "generator_function_declaration",
            "class_declaration",
            "export_statement",
            "lexical_declaration",
            "variable_declaration",
        )

        for node in tree.root_node.children:
            if node.type in target_types:
                start = node.start_point.row
                end = node.end_point.row + 1
                chunk_code = "\n".join(lines[start:end])
                if not chunk_code.strip():
                    continue

                name = ""
                # Try finding identifier or name child
                for c in node.children:
                    if c.type in ("identifier", "type_identifier", "name"):
                        name = code_text[c.start_byte : c.end_byte]
                        break

                meta = {
                    "source_file": source_file,
                    "type": node.type,
                    "name": name or f"block_{start+1}",
                    "start_line": start + 1,
                    "end_line": end,
                }
                if schema:
                    extracted = schema.extract(chunk_code)
                    meta.update({k: v for k, v in extracted.items() if v is not None})

                section_name = f"{node.type.replace('_', ' ').title()} {name}".strip()
                chunks.append(
                    Chunk(
                        text=chunk_code,
                        source_file=source_file,
                        page_or_section=section_name,
                        chunk_index=chunk_idx,
                        metadata=meta,
                    )
                )
                chunk_idx += 1

        if not chunks:
            return self._parse_generic_ast(code_text, source_file, schema)

        return chunks

    def _parse_tree_sitter_go(
        self, code_text: str, source_file: str, schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        try:
            import tree_sitter_go as tsgo
            from tree_sitter import Language, Parser

            go_lang = Language(tsgo.language())
            parser = Parser(go_lang)
            tree = parser.parse(code_text.encode("utf-8"))
        except Exception as e:
            logger.warning(f"Tree-sitter Go parse error on {source_file}: {e}; falling back.")
            return self._parse_generic_ast(code_text, source_file, schema)

        lines = code_text.splitlines()
        chunks: List[Chunk] = []
        chunk_idx = 0

        target_types = (
            "function_declaration",
            "method_declaration",
            "type_declaration",
        )

        for node in tree.root_node.children:
            if node.type in target_types:
                start = node.start_point.row
                end = node.end_point.row + 1
                chunk_code = "\n".join(lines[start:end])
                if not chunk_code.strip():
                    continue

                name = ""
                for c in node.children:
                    if c.type in ("identifier", "type_identifier", "name"):
                        name = code_text[c.start_byte : c.end_byte]
                        break

                meta = {
                    "source_file": source_file,
                    "type": node.type,
                    "name": name or f"block_{start+1}",
                    "start_line": start + 1,
                    "end_line": end,
                }
                if schema:
                    extracted = schema.extract(chunk_code)
                    meta.update({k: v for k, v in extracted.items() if v is not None})

                section_name = f"{node.type.replace('_', ' ').title()} {name}".strip()
                chunks.append(
                    Chunk(
                        text=chunk_code,
                        source_file=source_file,
                        page_or_section=section_name,
                        chunk_index=chunk_idx,
                        metadata=meta,
                    )
                )
                chunk_idx += 1

        if not chunks:
            return self._parse_generic_ast(code_text, source_file, schema)

        return chunks

    def _parse_generic_ast(
        self, code_text: str, source_file: str, schema: Optional[MetadataSchema] = None
    ) -> List[Chunk]:
        """Line-group chunking fallback for non-python or malformed syntax."""
        lines = code_text.splitlines()
        chunks: List[Chunk] = []
        step = 50
        chunk_idx = 0
        for i in range(0, max(1, len(lines)), step):
            group = lines[i : i + step]
            if not group or not "".join(group).strip():
                continue
            chunk_code = "\n".join(group)
            meta = {
                "source_file": source_file,
                "type": "block",
                "start_line": i + 1,
                "end_line": min(i + step, len(lines)),
            }
            if schema:
                extracted = schema.extract(chunk_code)
                meta.update({k: v for k, v in extracted.items() if v is not None})
            chunks.append(
                Chunk(
                    text=chunk_code,
                    source_file=source_file,
                    page_or_section=f"Lines {i+1}-{min(i+step, len(lines))}",
                    chunk_index=chunk_idx,
                    metadata=meta,
                )
            )
            chunk_idx += 1
        return chunks

    def parse(self, source: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(source, schema=schema)
