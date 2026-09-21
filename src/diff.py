"""Utility to evaluate and display response fidelity and semantic equivalence between cached and direct responses."""

import difflib
import math
from typing import Dict, Any


def compute_word_overlap_jaccard(text1: str, text2: str) -> float:
    """Compute Jaccard similarity coefficient on lowercased word tokens."""
    s1 = set(text1.lower().split())
    s2 = set(text2.lower().split())
    if not s1 or not s2:
        return 1.0 if s1 == s2 else 0.0
    return len(s1.intersection(s2)) / len(s1.union(s2))


def compare_responses(
    query: str,
    response_no_cache: str,
    response_with_cache: str,
    hit_type: str,
) -> Dict[str, Any]:
    """Compare direct LLM response vs cached response across key metrics."""
    # Exact equality check
    is_exact_match = (response_no_cache.strip() == response_with_cache.strip())
    
    # Jaccard lexical similarity
    jaccard_score = compute_word_overlap_jaccard(response_no_cache, response_with_cache)
    
    # Character & word length delta
    len_diff_chars = len(response_with_cache) - len(response_no_cache)
    words_no_cache = len(response_no_cache.split())
    words_with_cache = len(response_with_cache.split())
    
    # Sequence matcher similarity ratio
    seq_ratio = difflib.SequenceMatcher(None, response_no_cache, response_with_cache).ratio()
    
    # Qualitative classification
    if hit_type == "EXACT":
        diff_nature = "Bit-for-bit identical (Zero drift, 100% deterministic)"
    elif hit_type == "SEMANTIC":
        if is_exact_match:
            diff_nature = "Semantic Hit: Identical response reused"
        elif seq_ratio > 0.85:
            diff_nature = "Semantic Hit: Highly consistent answer with minimal phrasing variance"
        else:
            diff_nature = "Semantic Hit: Conceptually grounded answer reused across rephrased query"
    else:
        diff_nature = "Fresh generation (Cold miss / new question)"

    return {
        "query": query,
        "hit_type": hit_type,
        "is_exact_match": is_exact_match,
        "sequence_similarity": round(seq_ratio, 3),
        "jaccard_similarity": round(jaccard_score, 3),
        "length_diff_chars": len_diff_chars,
        "words_no_cache": words_no_cache,
        "words_with_cache": words_with_cache,
        "diff_nature": diff_nature,
    }


def format_side_by_side_diff(
    response_no_cache: str,
    response_with_cache: str,
    max_width: int = 45,
) -> str:
    """Format a clean side-by-side comparison block."""
    lines_no = [response_no_cache[i:i+max_width] for i in range(0, min(len(response_no_cache), 180), max_width)]
    lines_with = [response_with_cache[i:i+max_width] for i in range(0, min(len(response_with_cache), 180), max_width)]
    
    max_lines = max(len(lines_no), len(lines_with))
    lines_no += [""] * (max_lines - len(lines_no))
    lines_with += [""] * (max_lines - len(lines_with))
    
    title_left = "WITHOUT CACHE (Direct API)"
    title_right = "WITH CACHE (Intelligent Cache)"
    header = f"{title_left:<{max_width}} | {title_right:<{max_width}}"
    divider = "-" * (max_width * 2 + 3)
    rows = [header, divider]
    for left, right in zip(lines_no, lines_with):
        rows.append(f"{left:<{max_width}} | {right:<{max_width}}")
    return "\n".join(rows)
