"""OpenDocument Format (ODF) loader: .odt, .ods, .odp, .odg via odfpy.

Extracts body paragraphs/headings and table rows in document order, so text
documents, spreadsheets and presentations are all ingested without a
format-specific code path.
"""
import logging
import os
from typing import List, Optional

from ._common import coalesce, make_chunk
from .base import BaseLoader, Chunk
from ..core.metadata_guard import MetadataSchema

logger = logging.getLogger("ico_cache.loaders.odf_loader")

_MAX_CHUNK_CHARS = 2000


class ODFLoader(BaseLoader):
    """Loader for OpenDocument text/spreadsheet/presentation/graphics files."""

    def __init__(self, schema: Optional[MetadataSchema] = None, max_chunk_chars: int = _MAX_CHUNK_CHARS):
        self.schema = schema
        self.max_chunk_chars = max_chunk_chars

    def load(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        effective_schema = schema or self.schema
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return []
        try:
            from odf.opendocument import load as odf_load
            from odf import table as odf_table
            from odf.teletype import extractText
        except ImportError as e:  # pragma: no cover - depends on optional dep
            logger.warning("odfpy not installed; cannot parse %s: %s", file_path, e)
            return []

        try:
            document = odf_load(file_path)
        except Exception as e:
            logger.warning("Failed to open ODF document %s: %s", file_path, e)
            return []

        chunks: List[Chunk] = []
        roots = [
            root
            for root in (
                getattr(document, "text", None),
                getattr(document, "spreadsheet", None),
                getattr(document, "presentation", None),
                getattr(document, "drawing", None),
            )
            if root is not None
        ]
        if not roots:
            logger.warning("ODF document has no readable body: %s", file_path)
            return []

        table_idx = 0
        try:
            for root in roots:
                for kind, element in self._iter_blocks(root):
                    if kind == "text":
                        self._append_text(chunks, element, extractText, file_path, effective_schema)
                    else:
                        table_idx += 1
                        self._append_table(
                            chunks,
                            element,
                            odf_table,
                            extractText,
                            file_path,
                            effective_schema,
                            table_label=f"Table {table_idx}",
                        )
        except Exception as e:
            logger.warning("Failed while parsing ODF document %s: %s", file_path, e)
            return chunks
        return chunks

    _TEXT_TAGS = {"text:p", "text:h"}
    _TABLE_TAGS = {"table:table"}

    @staticmethod
    def _iter_blocks(node):
        """Yield body blocks (paragraphs/headings, tables) in document order."""
        for child in getattr(node, "childNodes", []):
            tag = getattr(child, "tagName", None)
            if tag in ODFLoader._TEXT_TAGS:
                yield "text", child
            elif tag in ODFLoader._TABLE_TAGS:
                yield "table", child
            else:
                yield from ODFLoader._iter_blocks(child)

    def _append_text(self, chunks, element, extractText, file_path, schema):
        text = (extractText(element) or "").strip()
        if not text:
            return
        for block in coalesce([text], self.max_chunk_chars):
            chunks.append(
                make_chunk(
                    block,
                    file_path,
                    f"Section {len(chunks) + 1}",
                    len(chunks),
                    "odf",
                    schema,
                )
            )

    def _append_table(self, chunks, table_el, odf_table, extractText, file_path, schema, table_label):
        rows = self._table_rows(table_el, odf_table, extractText)
        if not rows:
            return
        headers = None
        if len(rows) > 1:
            headers = [h if h else f"col{j + 1}" for j, h in enumerate(rows[0])]
            data_rows = rows[1:]
        else:
            data_rows = rows

        for row_idx, row in enumerate(data_rows, start=1):
            if headers:
                lines = [
                    f"{headers[j] if j < len(headers) else f'col{j + 1}'}: {cell}"
                    for j, cell in enumerate(row)
                ]
            else:
                lines = [f"col{j + 1}: {cell}" for j, cell in enumerate(row)]
            text = "\n".join([line for line in lines if line])
            if not text:
                continue
            chunks.append(
                make_chunk(
                    text,
                    file_path,
                    f"{table_label} Row {row_idx}",
                    len(chunks),
                    "odf_table",
                    schema,
                )
            )

    @staticmethod
    def _table_rows(table_el, odf_table, extractText) -> List[List[str]]:
        rows: List[List[str]] = []
        for row in table_el.getElementsByType(odf_table.TableRow):
            cells: List[str] = []
            for cell in row.getElementsByType(odf_table.TableCell):
                value = (extractText(cell) or "").strip()
                if not value:
                    raw = cell.getAttribute("value")
                    if raw is not None:
                        value = str(raw)
                cells.append(value)
            if any(cells):
                rows.append(cells)
        return rows

    def parse(self, file_path: str, schema: Optional[MetadataSchema] = None) -> List[Chunk]:
        return self.load(file_path, schema=schema)
