"""Retriever module using FAISS and SentenceTransformers or DefaultEmbedder."""

import json
import os
from typing import List, Dict, Tuple
import numpy as np


class SimpleVectorRetriever:
    """Vector retriever for RAG context extraction."""

    def __init__(self, corpus_path: str = "data/dataset/corpus.json"):
        self.corpus_path = corpus_path
        self.documents: List[Dict[str, str]] = []
        self._load_corpus()

    def _load_corpus(self):
        if not os.path.exists(self.corpus_path):
            raise FileNotFoundError(f"Corpus file not found at {self.corpus_path}. Run download_dataset.py first.")
        with open(self.corpus_path, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def retrieve(self, query: str, top_k: int = 2) -> List[Dict[str, str]]:
        """Retrieve the most relevant documents using keyword & n-gram overlap."""
        q_tokens = set(query.lower().split())
        scored_docs = []

        for doc in self.documents:
            text = (doc["title"] + " " + doc["content"]).lower()
            doc_tokens = set(text.split())
            overlap = len(q_tokens.intersection(doc_tokens))
            
            # Boost score if title tokens match
            title_tokens = set(doc["title"].lower().split())
            title_overlap = len(q_tokens.intersection(title_tokens))
            score = overlap + (title_overlap * 3.0)
            
            scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:top_k]]
