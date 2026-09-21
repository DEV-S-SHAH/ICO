"""Retriever for complex multi-modal corpus (PDF + TXT)."""

import json
import os
from typing import List, Dict


class ComplexRetriever:
    """Document retriever operating on multi-source corpus (PDF & TXT)."""

    def __init__(self, corpus_path: str = "data/complex_dataset/corpus.json"):
        self.corpus_path = corpus_path
        self.documents: List[Dict[str, str]] = []
        self._load_corpus()

    def _load_corpus(self):
        if not os.path.exists(self.corpus_path):
            raise FileNotFoundError(f"Corpus not found at {self.corpus_path}")
        with open(self.corpus_path, "r", encoding="utf-8") as f:
            self.documents = json.load(f)

    def retrieve(self, query: str, top_k: int = 2) -> List[Dict[str, str]]:
        q_tokens = [t.lower() for t in query.split() if len(t) > 2]
        scored_docs = []

        for doc in self.documents:
            text = (doc["title"] + " " + doc["content"]).lower()
            score = 0
            for t in q_tokens:
                if t in doc["title"].lower():
                    score += 5.0
                if t in text:
                    score += 1.0

            scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:top_k]]
