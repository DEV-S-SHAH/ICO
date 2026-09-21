"""Demo script comparing response differences, consistency, and semantic alignment."""

from response_diff import compare_responses, format_side_by_side_diff


def run_diff_showcase():
    print("=" * 85)
    print("  RESPONSE DIFFERENCE & DRIFT SHOWCASE: WITH VS WITHOUT CACHE")
    print("=" * 85)

    cases = [
        {
            "category": "Case 1: Exact Query Repeat (Zero Drift)",
            "query": "What is the Transformer network architecture based on?",
            "hit_type": "EXACT",
            "no_cache": (
                "The Transformer architecture is based entirely on self-attention mechanisms, "
                "dispensing with recurrence and convolutions."
            ),
            "with_cache": (
                "The Transformer architecture is based entirely on self-attention mechanisms, "
                "dispensing with recurrence and convolutions."
            ),
        },
        {
            "category": "Case 2: Rephrased Query (Semantic Hit)",
            "query": "Can you explain what Transformer is based upon according to the paper?",
            "hit_type": "SEMANTIC",
            "no_cache": (
                "According to the paper, the Transformer is a model architecture relying solely on "
                "an attention mechanism to draw global dependencies between input and output without recurrences."
            ),
            "with_cache": (
                "The Transformer architecture is based entirely on self-attention mechanisms, "
                "dispensing with recurrence and convolutions."
            ),
        },
        {
            "category": "Case 3: Inherent LLM Non-Determinism (Without Cache Drift)",
            "query": "What is Retrieval-Augmented Generation?",
            "hit_type": "EXACT",
            "no_cache": (
                "RAG is an AI framework that augments LLM prompts with external documents to ground responses."
            ),
            "with_cache": (
                "Retrieval-augmented generation (RAG) is a technique that enables large language models "
                "to retrieve factual external knowledge."
            ),
        },
    ]

    for c in cases:
        diff = compare_responses(
            query=c["query"],
            response_no_cache=c["no_cache"],
            response_with_cache=c["with_cache"],
            hit_type=c["hit_type"],
        )
        print(f"\n[{c['category']}]")
        print(f"  User Query:          '{c['query']}'")
        print(f"  Behavior:            {diff['diff_nature']}")
        print(f"  Text Match:          {'100% Exact Match' if diff['is_exact_match'] else 'Semantic Equivalence'}")
        print(f"  Sequence Similarity: {diff['sequence_similarity'] * 100:.1f}%")
        print(f"  Vocabulary Overlap:  {diff['jaccard_similarity'] * 100:.1f}%")
        print("\n  Side-by-Side Comparison:")
        print(format_side_by_side_diff(c["no_cache"], c["with_cache"], max_width=38))
        print("-" * 85)


if __name__ == "__main__":
    run_diff_showcase()
