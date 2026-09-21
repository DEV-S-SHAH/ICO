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
        q_tokens = [t.lower().strip(",.?!:;()[]") for t in query.split() if len(t) > 2]
        scored_docs = []

        for doc in self.documents:
            content_lower = doc["content"].lower()
            title_lower = doc["title"].lower()
            score = 0.0

            for t in q_tokens:
                # Content match with frequency weighting
                cnt = content_lower.count(t)
                if cnt > 0:
                    # Specialized keywords receive higher weighting than generic terms
                    weight = 1.0 if t in ("paper", "what", "how", "the") else 3.0
                    score += weight * min(cnt, 5)
                
                # Title exact match
                if t in title_lower:
                    score += 2.0

            scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:top_k]]
