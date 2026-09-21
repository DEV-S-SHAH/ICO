"""Default zero-dependency lightweight feature hashing embedder."""

import math
import re
from typing import Sequence
from intelligent_cache.embeddings.base import BaseEmbedder

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me",
    "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over",
    "own", "s", "same", "she", "should", "so", "some", "such", "t", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while",
    "who", "whom", "why", "will", "with", "you", "your", "yours", "yourself",
    "yourselves", "please", "tell", "show",
}

SUFFIXES = (
    "ing", "tion", "tions", "ment", "ments", "ance", "ence", "able", "ible",
    "ive", "ous", "ful", "less", "ly", "ed", "er", "ers", "es", "s"
)


class DefaultEmbedder(BaseEmbedder):
    """Fast, zero-dependency, deterministic n-gram and token feature hashing embedder.
    
    Produces normalized dense vectors suitable for semantic similarity search without
    requiring PyTorch, HuggingFace transformers, or external API calls.
    """

    def __init__(self, dimension: int = 256):
        self._dim = dimension
        self._word_regex = re.compile(r"\b[a-zA-Z0-9_-]+\b")

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"DefaultEmbedder({self._dim})"

    def _stem(self, word: str) -> str:
        """Lightweight Porter-like suffix stripping for semantic normalization."""
        for suffix in SUFFIXES:
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                return word[:-len(suffix)]
        return word

    def _hash_feature(self, feature: str, seed: int = 0) -> tuple[int, float]:
        """Hash a feature string into a (bucket_index, sign) pair."""
        h = 2166136261 ^ seed
        for ch in feature:
            h = (h ^ ord(ch)) * 16777619
            h &= 0xFFFFFFFF
        bucket = h % self._dim
        sign = 1.0 if (h >> 16) & 1 == 0 else -1.0
        return bucket, sign

    def embed(self, text: str) -> list[float]:
        """Embed a text string into a normalized dense vector."""
        if not text:
            return [0.0] * self._dim

        vector = [0.0] * self._dim
        text_lower = text.lower()
        words = self._word_regex.findall(text_lower)

        if not words:
            return [0.0] * self._dim

        word_counts: dict[str, int] = {}
        stem_counts: dict[str, int] = {}
        ngram_counts: dict[str, int] = {}

        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
            st = self._stem(w)
            stem_counts[st] = stem_counts.get(st, 0) + 1

            # Subword character n-grams
            w_padded = f"^{st}$"
            for n in (3, 4):
                if len(w_padded) >= n:
                    for i in range(len(w_padded) - n + 1):
                        ngram = w_padded[i : i + n]
                        ngram_counts[ngram] = ngram_counts.get(ngram, 0) + 1

        # Hash stems with high weight for content words, low weight for stopwords
        for st, count in stem_counts.items():
            base_wt = 0.5 if st in STOPWORDS else 4.0
            weight = base_wt * (1.0 + math.log(count))
            idx, sign = self._hash_feature(f"stem:{st}", seed=42)
            vector[idx] += sign * weight

        # Hash full words
        for word, count in word_counts.items():
            base_wt = 0.3 if word in STOPWORDS else 2.5
            weight = base_wt * (1.0 + math.log(count))
            idx, sign = self._hash_feature(f"word:{word}", seed=1337)
            vector[idx] += sign * weight

        # Hash character n-grams with moderate weight
        for ngram, count in ngram_counts.items():
            weight = 0.8 * (1.0 + math.log(count))
            idx, sign = self._hash_feature(f"ng:{ngram}", seed=999)
            vector[idx] += sign * weight

        # L2 normalize vector
        norm_sq = sum(v * v for v in vector)
        if norm_sq > 0.0:
            inv_norm = 1.0 / math.sqrt(norm_sq)
            vector = [v * inv_norm for v in vector]

        return vector

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
