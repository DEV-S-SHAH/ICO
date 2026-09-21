"""LangGraph RAG Application with IntelligentCache Layer and Google Gemini."""

import os
import time
from typing import TypedDict, List, Dict, Optional
import google.generativeai as genai
from langgraph.graph import StateGraph, START, END

from intelligent_cache import IntelligentCache
from intelligent_cache.core.decorator import cache
from src.retriever import ComplexRetriever

# Configure Google Gemini
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY", 
    "AQ.Ab8RN6I7YbIFGTAbO1W-legybOb3gaJl81P0mKU5s3M7Rp1ofA"
)
genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel("gemini-3.1-flash-lite")

# Global IntelligentCache instance with high-precision threshold
intelligent_cache_instance = IntelligentCache(
    similarity_threshold=0.88,
    default_ttl=3600,
    namespace="langgraph_rag",
)


def _invoke_gemini_with_retry(prompt: str, max_retries: int = 5) -> str:
    delay = 2.0
    for attempt in range(max_retries):
        try:
            resp = _gemini_model.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


# Define LangGraph State
class RAGState(TypedDict):
    question: str
    documents: List[Dict[str, str]]
    answer: str
    use_cache: bool
    latency_ms: float
    from_cache: bool


# Initialize retriever
_retriever = ComplexRetriever()


def retrieve_node(state: RAGState) -> Dict:
    """Node 1: Retrieve context documents from the dataset."""
    question = state["question"]
    docs = _retriever.retrieve(question, top_k=2)
    return {"documents": docs}


def generate_node(state: RAGState) -> Dict:
    """Node 2: Synthesize answer using context and Gemini LLM with high-precision caching."""
    question = state["question"]
    docs = state.get("documents", [])
    use_cache = state.get("use_cache", True)

    doc_ids = ",".join(sorted([d.get("doc_id", d.get("title", "")) for d in docs]))
    namespace = f"langgraph_rag:{doc_ids}"
    context_str = "\n\n".join([f"[{d['title']}]: {d['content']}" for d in docs])
    prompt = (
        "You are a helpful AI assistant. Answer the user's question concisely based on the provided context.\n\n"
        f"Context:\n{context_str}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )

    t0 = time.perf_counter()
    is_hit = False

    if use_cache:
        # Check cache scoped to the specific document context using 0.88 threshold
        hit = intelligent_cache_instance.get(
            query=question.strip().lower(),
            namespace=namespace,
            threshold=0.88,
        )
        if hit is not None:
            answer = hit.value
            is_hit = True
        else:
            answer = _invoke_gemini_with_retry(prompt)
            intelligent_cache_instance.set(
                query=question.strip().lower(),
                value=answer,
                namespace=namespace,
                ttl=3600,
                apply_policy=False,
            )
    else:
        answer = _invoke_gemini_with_retry(prompt)

    latency = (time.perf_counter() - t0) * 1000.0

    return {
        "answer": answer,
        "latency_ms": round(latency, 2),
        "from_cache": is_hit,
    }


def build_rag_graph():
    """Build and compile the LangGraph workflow."""
    workflow = StateGraph(RAGState)

    # Add nodes
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)

    # Add edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    return workflow.compile()


rag_app = build_rag_graph()


def query_rag(question: str, use_cache: bool = True) -> RAGState:
    """Execute the compiled LangGraph RAG application."""
    initial_state = {
        "question": question,
        "documents": [],
        "answer": "",
        "use_cache": use_cache,
        "latency_ms": 0.0,
        "from_cache": False,
    }
    return rag_app.invoke(initial_state)
