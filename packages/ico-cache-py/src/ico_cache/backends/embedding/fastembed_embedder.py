from fastembed import TextEmbedding
from typing import List
from ..base import BaseEmbedder

class FastEmbedder(BaseEmbedder):
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model = TextEmbedding(model_name=model_name)

    def embed(self, text: str) -> List[float]:
        return list(self.model.embed([text]))[0].tolist()
