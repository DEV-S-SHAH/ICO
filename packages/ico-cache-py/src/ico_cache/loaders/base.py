from abc import ABC, abstractmethod
from typing import Any, Dict, List
from pydantic import BaseModel, Field


class Chunk(BaseModel):
    text: str
    source_file: str
    page_or_section: str = ""
    chunk_index: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


TextChunk = Chunk


class BaseLoader(ABC):
    @abstractmethod
    def load(self, source: str) -> List[Chunk]:
        """Loads and chunks content from source (file path, URI, connection, etc.)."""
        pass

    def parse(self, file_path: str) -> List[Chunk]:
        """Backward-compatible alias for load()."""
        return self.load(file_path)


BaseDocumentParser = BaseLoader
