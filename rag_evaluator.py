"""RAG Evaluation Suite: Faithfulness, Answer Relevance, Context Precision, and ROUGE/Semantic Equivalence."""

import json
import re
from typing import Dict, List, Any
from rouge_score import rouge_scorer


def compute_token_f1(prediction: str, ground_truth: str) -> float:
    """Compute token-level precision, recall, and F1 score."""
    pred_tokens = re.findall(r"\w+", prediction.lower())
    truth_tokens = re.findall(r"\w+", ground_truth.lower())

    if not pred_tokens or not truth_tokens:
        return 1.0 if pred_tokens == truth_tokens else 0.0

    common = set(pred_tokens) & set(truth_tokens)
    num_same = sum(min(pred_tokens.count(t), truth_tokens.count(t)) for t in common)
    if num_same == 0:
        return 0.0

    precision = 1.0 * num_same / len(pred_tokens)
    recall = 1.0 * num_same / len(truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return round(f1, 4)


class RAGEvaluator:
    """Comprehensive evaluation suite for RAG responses."""

    def __init__(self):
        self.rouge = rouge_scorer.RougeScorer(["rouge1", "rougeL"], use_stemmer=True)

    def evaluate_faithfulness(self, response: str, contexts: List[str]) -> float:
        """Measure what percentage of statements/facts in the response are grounded in the retrieved context."""
        context_blob = " ".join(contexts).lower()
        context_words = set(re.findall(r"\w+", context_blob))

        sentences = [s.strip() for s in re.split(r"[.!?]", response) if len(s.strip()) > 10]
        if not sentences:
            return 1.0

        grounded_count = 0
        for sent in sentences:
            sent_words = [w for w in re.findall(r"\w+", sent.lower()) if len(w) > 3]
            if not sent_words:
                continue
            matched = sum(1 for w in sent_words if w in context_words)
            if (matched / len(sent_words)) >= 0.40:  # Key facts found in context
                grounded_count += 1

        return round(min(1.0, grounded_count / max(1, len(sentences))), 3)

    def evaluate_answer_relevance(self, query: str, response: str) -> float:
        """Measure relevance of response to the query using lexical and topical alignment."""
        q_tokens = set(re.findall(r"\w+", query.lower())) - {
            "what", "is", "the", "how", "does", "can", "you", "explain", "in", "and", "of", "to"
        }
        if not q_tokens:
            return 1.0

        r_tokens = set(re.findall(r"\w+", response.lower()))
        matched = q_tokens & r_tokens
        return round(len(matched) / len(q_tokens), 3)

    def evaluate_pair(
        self,
        query: str,
        response_no_cache: str,
        response_with_cache: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """Run full evaluation suite comparing direct response against cached response."""
        # 1. Faithfulness (Groundedness in context)
        faith_no = self.evaluate_faithfulness(response_no_cache, contexts)
        faith_with = self.evaluate_faithfulness(response_with_cache, contexts)

        # 2. Answer Relevance
        rel_no = self.evaluate_answer_relevance(query, response_no_cache)
        rel_with = self.evaluate_answer_relevance(query, response_with_cache)

        # 3. ROUGE & Semantic Equivalence
        rouge_res = self.rouge.score(response_no_cache, response_with_cache)
        rouge1_f1 = round(rouge_res["rouge1"].fmeasure, 3)
        rougeL_f1 = round(rouge_res["rougeL"].fmeasure, 3)
        token_f1 = compute_token_f1(response_with_cache, response_no_cache)

        # 4. Composite Quality Score (0 to 1.0)
        quality_no = round((faith_no * 0.6) + (rel_no * 0.4), 3)
        quality_with = round((faith_with * 0.6) + (rel_with * 0.4), 3)

        return {
            "faithfulness_no_cache": faith_no,
            "faithfulness_with_cache": faith_with,
            "relevance_no_cache": rel_no,
            "relevance_with_cache": rel_with,
            "composite_quality_no_cache": quality_no,
            "composite_quality_with_cache": quality_with,
            "rouge1_f1": rouge1_f1,
            "rougeL_f1": rougeL_f1,
            "token_f1": token_f1,
            "quality_parity": quality_with >= (quality_no - 0.05),
        }
