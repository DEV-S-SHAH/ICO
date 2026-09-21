"""Vector similarity calculations and search utilities."""

import math
from typing import Any, Callable, Optional, Sequence

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    if _HAS_NUMPY:
        a = np.asarray(vec_a, dtype=np.float32)
        b = np.asarray(vec_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        val = float(np.dot(a, b) / (norm_a * norm_b))
        return max(-1.0, min(1.0, val))

    dot = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a_sq += a * a
        norm_b_sq += b * b

    if norm_a_sq == 0.0 or norm_b_sq == 0.0:
        return 0.0

    denom = math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq)
    sim = dot / denom
    return max(-1.0, min(1.0, sim))


def euclidean_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate normalized similarity based on Euclidean distance: 1 / (1 + dist)."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    if _HAS_NUMPY:
        a = np.asarray(vec_a, dtype=np.float32)
        b = np.asarray(vec_b, dtype=np.float32)
        dist = float(np.linalg.norm(a - b))
        return 1.0 / (1.0 + dist)

    dist_sq = 0.0
    for a, b in zip(vec_a, vec_b):
        diff = a - b
        dist_sq += diff * diff

    dist = math.sqrt(dist_sq)
    return 1.0 / (1.0 + dist)


def dot_product_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Calculate dot product between two vectors (normalized to [-1, 1] if vectors are unit)."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    if _HAS_NUMPY:
        a = np.asarray(vec_a, dtype=np.float32)
        b = np.asarray(vec_b, dtype=np.float32)
        return float(np.dot(a, b))

    return sum(a * b for a, b in zip(vec_a, vec_b))


SIMILARITY_FUNCTIONS: dict[str, Callable[[Sequence[float], Sequence[float]], float]] = {
    "cosine": cosine_similarity,
    "euclidean": euclidean_similarity,
    "dot": dot_product_similarity,
}


def find_top_matches(
    query_vector: Sequence[float],
    candidates: Sequence[tuple[Any, Sequence[float]]],
    threshold: float = 0.85,
    top_k: int = 1,
    metric: str = "cosine",
) -> list[tuple[Any, float]]:
    """Find top matching items exceeding similarity threshold.
    
    Args:
        query_vector: The query embedding vector.
        candidates: Sequence of (item, vector) tuples.
        threshold: Minimum similarity threshold (e.g. 0.85).
        top_k: Maximum number of matches to return.
        metric: Similarity metric ('cosine', 'euclidean', 'dot').
        
    Returns:
        List of (item, similarity_score) sorted descending by score.
    """
    sim_fn = SIMILARITY_FUNCTIONS.get(metric.lower(), cosine_similarity)
    scored: list[tuple[Any, float]] = []

    for item, vector in candidates:
        if vector is None or len(vector) != len(query_vector):
            continue
        sim = sim_fn(query_vector, vector)
        if sim >= threshold:
            scored.append((item, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
