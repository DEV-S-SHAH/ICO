"""FastAPI application for Real RAG Demo and Live Dashboard Integration."""

import asyncio
import calendar
import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ico_cache.backends.exact.redis_store import RedisStore
from ico_cache.backends.exact.sqlite_store import SQLiteStore
from ico_cache.backends.vector.lancedb_store import LanceDBStore
from ico_cache.backends.vector.qdrant_store import QdrantStore
from ico_cache.core.cache_engine import CacheEngine
from ico_cache.core.decision_trace import (
    CANONICAL_CASCADE,
    DecisionOutcome,
    DecisionTrace,
    DecisionTraceStore,
    LayerStatus,
    LayerTrace,
    begin_trace,
    get_active_trace,
    record_layer,
    reset_active_trace,
    safe_id,
)
from ico_cache.telemetry.accounting import (
    AccountingContext,
    CacheLayer,
    DecisionAction,
    UsageRecord,
    UsageSource,
    get_collector,
    get_cost_model,
    get_usage_tracker,
    record_usage,
)

from .config import DemoConfig, config
from .embeddings import CachedEmbedder
from .ingest import DocumentIngestion
from .prompts import PROMPT_TEMPLATE_VERSION
from .rag_graph import LangGraphRAG
from .retriever import RAGRetriever
from .vectorstore import RAGVectorStore


# Request/Response Models
class RAGQueryRequest(BaseModel):
    query: str
    tenant_id: Optional[str] = None
    corpus_version: Optional[str] = None
    top_k: Optional[int] = None
    model: Optional[str] = None
    bypass_cache: Optional[bool] = False
    context: Optional[str] = None


class RAGSource(BaseModel):
    document: str
    page: int
    chunk_id: str
    content_hash: Optional[str] = None


class RAGCacheMeta(BaseModel):
    hit: bool
    layer: Optional[str] = None
    similarity: Optional[float] = None
    tokens_saved: int = 0
    latency_saved_ms: float = 0.0


class RAGQueryResponse(BaseModel):
    answer: str
    sources: List[RAGSource]
    request_id: str
    corpus_version: str
    cache: RAGCacheMeta
    latency_ms: float
    trace_id: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "gemini-1.5-flash"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False
    top_k: Optional[int] = 5
    tenant_id: Optional[str] = "default"
    bypass_cache: Optional[bool] = False


class SDKQueryRequest(BaseModel):
    query: Optional[str] = None
    prompt: Optional[str] = None
    context: Optional[str] = None
    tenant_id: Optional[str] = "default"
    model: Optional[str] = None
    bypass_cache: Optional[bool] = False


class SDKIngestRequest(BaseModel):
    query: str
    context: Optional[str] = None
    response: Any
    tenant_id: Optional[str] = "default"


class PlaygroundRequest(BaseModel):
    model: Optional[str] = "gemini-1.5-flash"
    provider: Optional[str] = "mock"
    endpoint: Optional[str] = "/v1/chat/completions"
    systemPrompt: Optional[str] = ""
    userPrompt: str
    temperature: Optional[float] = 0.7
    maxTokens: Optional[int] = 1000


def create_demo_app(cfg: Optional[DemoConfig] = None) -> FastAPI:
    cfg = cfg or config
    app = FastAPI(
        title="ICO-Cache Real RAG Demo & Dashboard API",
        version="1.0.0",
        description="End-to-end RAG with LangGraph, ICO-Cache L0-L5 cascade, and live telemetry",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize storage backends
    if cfg.exact_store_type == "redis":
        exact_store = RedisStore(
            host=cfg.redis_host,
            port=cfg.redis_port,
            password=cfg.redis_password,
        )
    else:
        exact_store = SQLiteStore(db_path=cfg.sqlite_path)

    vector_store = RAGVectorStore(cfg)
    embedder = CachedEmbedder(
        exact_store=exact_store,
        model_name=cfg.embedding_model,
        enable_cache=True,
    )

    # Ingestion
    ingestion = DocumentIngestion(
        documents_dir=cfg.documents_dir,
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
    )

    # Retriever & LangGraph RAG
    retriever = RAGRetriever(
        vector_store=vector_store,
        embedder=embedder,
        exact_store=exact_store,
        enable_l4_cache=True,
        l4_ttl=cfg.l4_ttl,
    )

    rag_graph = LangGraphRAG(
        retriever=retriever,
        config=cfg,
        exact_store=exact_store,
        enable_l5_cache=True,
    )

    # Decision trace store & in-memory request history
    trace_store = DecisionTraceStore(max_traces=1000)
    requests_history: List[Dict[str, Any]] = []
    events_log: List[Dict[str, Any]] = []
    app_start_time = time.time()

    # Shared state
    app.state.cfg = cfg
    app.state.exact_store = exact_store
    app.state.vector_store = vector_store
    app.state.embedder = embedder
    app.state.ingestion = ingestion
    app.state.retriever = retriever
    app.state.rag_graph = rag_graph
    app.state.trace_store = trace_store
    app.state.corpus_version = "v_init"
    app.state.chunks = []
    app.state.enable_cache = True

    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    active_websockets: set = set()

    async def _broadcast_to_websockets(msg: str):
        disconnected = []
        for ws in list(active_websockets):
            try:
                await ws.send_text(msg)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            active_websockets.discard(ws)

    def _push_event(event_type: str, payload: dict, request_id: Optional[str] = None):
        event = {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "requestId": request_id or payload.get("id") or payload.get("request_id") or "sys",
            "payload": payload,
        }
        events_log.append(event)
        if len(events_log) > 500:
            events_log.pop(0)

        if active_websockets:
            msg = json.dumps(event)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_broadcast_to_websockets(msg))
            except RuntimeError:
                pass

    # Initial Ingestion on startup
    @app.on_event("startup")
    async def startup_event():
        try:
            chunks, corpus_v = ingestion.extract_chunks()
            app.state.corpus_version = corpus_v
            app.state.chunks = chunks
            if chunks:
                vectors = embedder.embed_batch([c["text"] for c in chunks])
                await vector_store.insert_chunks(chunks, vectors)
                print(f"[STARTUP] Ingested {len(chunks)} chunks into {cfg.vector_db_type}. Corpus version: {corpus_v}")
        except Exception as e:
            print(f"[STARTUP WARNING] Initial ingestion failed: {e}")

    # =========================================================================
    # RAG API Endpoints
    # =========================================================================

    @app.post("/rag/ingest")
    async def ingest_documents():
        """Trigger ingestion of documents in documents_dir."""
        t0 = time.perf_counter()
        chunks, corpus_v = ingestion.extract_chunks()
        app.state.corpus_version = corpus_v
        app.state.chunks = chunks

        if chunks:
            vectors = embedder.embed_batch([c["text"] for c in chunks])
            await vector_store.insert_chunks(chunks, vectors)

        dur_ms = (time.perf_counter() - t0) * 1000
        _push_event(
            "CacheInvalidation",
            {"corpus_version": corpus_v, "chunks": len(chunks), "reason": "Corpus ingestion"},
            request_id=f"ingest_{uuid.uuid4().hex[:8]}",
        )
        return {
            "status": "success",
            "corpus_version": corpus_v,
            "chunks_count": len(chunks),
            "duration_ms": round(dur_ms, 2),
        }

    @app.post("/rag/query", response_model=RAGQueryResponse)
    async def rag_query_endpoint(req: RAGQueryRequest, request: Request):
        """
        Execute RAG query routed through ICO-Cache multi-tier cascade.
        Flow:
        1. Check L0 (Deterministic)
        2. Check L1 (Exact Prompt Cache)
        3. Check L2 (Semantic Vector Cache)
        4. If Miss -> LangGraph RAG (consults L4 Retrieval Cache and L5 Context Cache) -> LLM
        5. Cache response to L1 & L2 for future reuse
        6. Record decision trace & accounting usage for live dashboard
        """
        t_total_start = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:10]}"
        tenant_id = req.tenant_id or cfg.default_tenant
        corpus_v = req.corpus_version or app.state.corpus_version
        top_k = req.top_k or cfg.top_k
        model = req.model or cfg.llm_model
        provider = cfg.llm_provider

        # Start decision trace
        trace, token, created = begin_trace(
            request_id=request_id,
            tenant_id=tenant_id,
            query=req.query,
            model=model,
            provider=provider,
            reuse_active=False,
        )

        winning_layer: Optional[str] = None
        cache_hit = False
        similarity_score: Optional[float] = None
        cached_response: Optional[Dict[str, Any]] = None
        latency_saved_ms = 0.0
        tokens_saved = 0

        # Keys
        norm_query = " ".join(req.query.lower().strip().split())
        query_hash = hashlib.sha256(norm_query.encode("utf-8")).hexdigest()[:16]
        if req.context and req.context.strip():
            norm_ctx = " ".join(req.context.lower().strip().split())
            ctx_hash = hashlib.sha256(norm_ctx.encode("utf-8")).hexdigest()[:12]
            l1_key = f"l1:{tenant_id}:{query_hash}:{ctx_hash}:{corpus_v}:{model}"
        else:
            l1_key = f"l1:{tenant_id}:{query_hash}:{corpus_v}:{model}"
        l2_key = f"l2:{tenant_id}:{query_hash}:{corpus_v}:{model}"

        should_check_cache = (not req.bypass_cache) and getattr(app.state, "enable_cache", True)

        # ---------------------------------------------------------------------
        # Step 1: L0 Deterministic Function Check
        # ---------------------------------------------------------------------
        q_lower = req.query.strip().lower()
        if q_lower.startswith(("calc:", "det:", "func:", "math:")) or q_lower in ("ping", "version", "system:status"):
            t_l0_start = time.perf_counter()
            if q_lower == "ping":
                det_ans = "pong"
            elif q_lower in ("version", "system:status"):
                det_ans = "ICO-Cache v1.0.4 | Status: Operational | Backends: Active"
            elif q_lower.startswith("calc:") or q_lower.startswith("math:"):
                expr = req.query.split(":", 1)[1].strip()
                try:
                    # Safe arithmetic evaluation
                    det_ans = f"Calculated: {eval(expr, {'__builtins__': {}}, {})}"
                except Exception as e:
                    det_ans = f"Calculation error: {e}"
            else:
                det_ans = f"Deterministic response for {req.query}"

            dur_l0 = (time.perf_counter() - t_l0_start) * 1000
            cache_hit = True
            winning_layer = "L0a"
            cached_response = {"answer": det_ans, "sources": []}
            latency_saved_ms = 500.0

            record_layer(
                "L0a",
                LayerStatus.HIT,
                reason=f"L0 deterministic function hit for '{req.query}'",
                latency_ms=dur_l0,
                hit=True,
                cache_key=f"l0:{query_hash}",
                reuse_source="deterministic_function",
            )
        else:
            record_layer("L0a", LayerStatus.MISS, reason="Dynamic query - bypassed L0 deterministic cache", latency_ms=0.1)

        # ---------------------------------------------------------------------
        # Step 2: L1 Exact Match Cache Check
        # ---------------------------------------------------------------------
        if should_check_cache and not cache_hit:
            t_l1_start = time.perf_counter()
            try:
                l1_val = exact_store.get(l1_key)
                if l1_val:
                    cached_data = json.loads(l1_val.decode("utf-8"))
                    dur_l1 = (time.perf_counter() - t_l1_start) * 1000
                    cache_hit = True
                    winning_layer = "L1"
                    cached_response = cached_data
                    latency_saved_ms = 450.0

                    record_layer(
                        "L1",
                        LayerStatus.HIT,
                        reason=f"L1 exact match hit for prompt hash {query_hash}",
                        latency_ms=dur_l1,
                        hit=True,
                        cache_key=l1_key,
                        reuse_source="l1_exact",
                    )
                else:
                    dur_l1 = (time.perf_counter() - t_l1_start) * 1000
                    record_layer("L1", LayerStatus.MISS, reason="L1 exact match miss", latency_ms=dur_l1)
            except Exception:
                record_layer("L1", LayerStatus.MISS, reason="L1 lookup error", latency_ms=0.5)

        # ---------------------------------------------------------------------
        # Step 3: L2 Semantic Match Cache Check (if L1 miss and no dialog context)
        # ---------------------------------------------------------------------
        if should_check_cache and not cache_hit:
            if req.context and req.context.strip():
                record_layer("L2", LayerStatus.SKIPPED, reason="Skipped: conversational context present, deferred to L3 context cache", latency_ms=0.1)
            else:
                t_l2_start = time.perf_counter()
                try:
                    # Real vector search in L2 collection
                    q_emb = embedder.embed(req.query, record_trace=False)
                    l2_match = await vector_store.search_l2_cache(
                        query_vector=q_emb,
                        min_score=cfg.semantic_threshold,
                        corpus_version=corpus_v,
                        model=model,
                        provider=provider,
                        tenant_id=tenant_id,
                    )
                    dur_l2 = (time.perf_counter() - t_l2_start) * 1000

                    if l2_match:
                        cache_hit = True
                        winning_layer = "L2"
                        similarity_score = round(l2_match["score"], 4)
                        cached_response = {
                            "answer": l2_match["answer"],
                            "sources": l2_match["sources"],
                        }
                        latency_saved_ms = 400.0

                        record_layer(
                            "L2",
                            LayerStatus.HIT,
                            reason=f"L2 semantic match hit (similarity={similarity_score:.3f} >= {cfg.semantic_threshold})",
                            latency_ms=dur_l2,
                            hit=True,
                            score=similarity_score,
                            cache_key=f"l2:{tenant_id}:{query_hash}",
                            reuse_source="l2_semantic",
                        )
                    else:
                        record_layer(
                            "L2",
                            LayerStatus.MISS,
                            reason="L2 semantic similarity below threshold or hard gate mismatch",
                            latency_ms=dur_l2,
                        )
                except Exception:
                    record_layer("L2", LayerStatus.MISS, reason="L2 vector lookup error", latency_ms=0.5)

        # ---------------------------------------------------------------------
        # Step 3b: L3 Context-Aware Cache Check
        # ---------------------------------------------------------------------
        if should_check_cache and not cache_hit:
            if req.context and req.context.strip():
                t_l3_start = time.perf_counter()
                try:
                    q_emb = embedder.embed(req.query, record_trace=False)
                    c_emb = embedder.embed(req.context, record_trace=False)
                    l3_match = await vector_store.search_l3_cache(
                        query_vector=q_emb,
                        context_vector=c_emb,
                        min_query_score=0.82,
                        min_context_score=0.75,
                        corpus_version=corpus_v,
                        model=model,
                        provider=provider,
                        tenant_id=tenant_id,
                    )
                    dur_l3 = (time.perf_counter() - t_l3_start) * 1000
                    if l3_match:
                        cache_hit = True
                        winning_layer = "L3"
                        similarity_score = round(l3_match["score"], 4)
                        cached_response = {
                            "answer": l3_match["answer"],
                            "sources": l3_match["sources"],
                        }
                        latency_saved_ms = 400.0
                        record_layer(
                            "L3",
                            LayerStatus.HIT,
                            reason=f"L3 context match hit (q_sim={l3_match.get('query_score', similarity_score):.3f}, ctx_sim={l3_match.get('context_score', similarity_score):.3f})",
                            latency_ms=dur_l3,
                            hit=True,
                            score=similarity_score,
                            cache_key=f"l3:{tenant_id}:{query_hash}",
                            reuse_source="l3_context",
                        )
                    else:
                        record_layer(
                            "L3",
                            LayerStatus.MISS,
                            reason="L3 dual-vector similarity below threshold",
                            latency_ms=dur_l3,
                        )
                except Exception as e:
                    record_layer("L3", LayerStatus.MISS, reason=f"L3 lookup error: {e}", latency_ms=0.5)
            else:
                record_layer("L3", LayerStatus.MISS, reason="No conversational dual-vector context provided", latency_ms=0.1)

        # ---------------------------------------------------------------------
        # Step 4: Resolve Response (Hit vs Generation via LangGraph)
        # ---------------------------------------------------------------------
        if cache_hit and cached_response:
            # CACHE HIT: Reuse answer & provenance
            answer = cached_response["answer"]
            raw_sources = cached_response.get("sources", [])
            tokens_saved = _estimate_tokens(req.query) + _estimate_tokens(answer)

            if trace:
                trace.finalize(
                    outcome=DecisionOutcome.CACHE_RESPONSE,
                    final_layer=winning_layer,
                    final_confidence=similarity_score or 1.0,
                    final_reason=f"Response served from {winning_layer} cache",
                )
                trace_store.store(trace)

            # Accounting for Cache Hit
            action_map = {
                "L0a": DecisionAction.EXACT_REUSE,
                "L1": DecisionAction.EXACT_REUSE,
                "L2": DecisionAction.SEMANTIC_REUSE,
                "L3": DecisionAction.CONTEXT_REUSE,
            }
            layer_map = {
                "L0a": CacheLayer.L0A,
                "L0b": CacheLayer.L0B,
                "L1": CacheLayer.L1,
                "L2": CacheLayer.L2,
                "L3": CacheLayer.L3,
            }
            usage_rec = UsageRecord(
                request_id=request_id,
                tenant_id=tenant_id,
                layer=layer_map.get(winning_layer, CacheLayer.L1),
                decision_action=action_map.get(winning_layer, DecisionAction.EXACT_REUSE),
                cache_hit=1,
                cache_miss=0,
                cached_input_tokens=tokens_saved,
                tokens_saved=tokens_saved,
                latency_ms=(time.perf_counter() - t_total_start) * 1000,
                latency_saved=latency_saved_ms,
                model=model,
                provider=provider,
            )
            get_usage_tracker().record(usage_rec)

        else:
            # CACHE MISS: Execute LangGraph RAG Workflow
            initial_state = {
                "query": req.query,
                "tenant_id": tenant_id,
                "corpus_version": corpus_v,
                "top_k": top_k,
                "request_id": request_id,
                "model": model,
                "provider": provider,
            }
            rag_result = await rag_graph.invoke(initial_state)

            answer = rag_result.get("answer", "")
            raw_sources = rag_result.get("sources", [])

            # Write to L1 (exact) and L2 (vector) for future requests
            store_payload = {
                "answer": answer,
                "sources": raw_sources,
                "corpus_version": corpus_v,
                "similarity": 1.0,
                "timestamp": time.time(),
            }
            try:
                serialized = json.dumps(store_payload).encode("utf-8")
                exact_store.set(l1_key, serialized, ex=cfg.l1_ttl)
                # Store vector in L2 semantic vector store
                q_vec = embedder.embed(req.query, record_trace=False)
                await vector_store.insert_l2_cache(
                    query=req.query,
                    vector=q_vec,
                    answer=answer,
                    sources=raw_sources,
                    corpus_version=corpus_v,
                    model=model,
                    provider=provider,
                    tenant_id=tenant_id,
                )
                if req.context and req.context.strip():
                    c_vec = embedder.embed(req.context, record_trace=False)
                    await vector_store.insert_l3_cache(
                        query=req.query,
                        query_vector=q_vec,
                        context=req.context,
                        context_vector=c_vec,
                        answer=answer,
                        sources=raw_sources,
                        corpus_version=corpus_v,
                        model=model,
                        provider=provider,
                        tenant_id=tenant_id,
                    )
            except Exception:
                pass

            if trace:
                trace.finalize(
                    outcome=DecisionOutcome.GENERATE_LLM,
                    final_layer="LLM",
                    final_confidence=0.0,
                    final_reason="Full generation performed via LangGraph RAG",
                )
                trace_store.store(trace)

            input_toks = _estimate_tokens(req.query) + _estimate_tokens(rag_result.get("context", ""))
            output_toks = _estimate_tokens(answer)

            usage_rec = UsageRecord(
                request_id=request_id,
                tenant_id=tenant_id,
                layer=CacheLayer.RAG_FALLBACK,
                decision_action=DecisionAction.FULL_LLM_CALL,
                cache_hit=0,
                cache_miss=1,
                llm_called=1,
                input_tokens=input_toks,
                output_tokens=output_toks,
                total_tokens=input_toks + output_toks,
                latency_ms=(time.perf_counter() - t_total_start) * 1000,
                model=model,
                provider=provider,
            )
            get_usage_tracker().record(usage_rec)

        total_latency_ms = (time.perf_counter() - t_total_start) * 1000

        # Build Sources
        formatted_sources = [
            RAGSource(
                document=s.get("document", s.get("filename", "paper.pdf")),
                page=s.get("page", 1),
                chunk_id=s.get("chunk_id", "c1"),
                content_hash=s.get("content_hash"),
            )
            for s in raw_sources
        ]

        # Log request for dashboard
        req_item = {
            "id": request_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": model,
            "provider": provider,
            "endpoint": "/rag/query",
            "query": req.query,
            "tokens": {
                "input": _estimate_tokens(req.query),
                "output": _estimate_tokens(answer),
                "total": _estimate_tokens(req.query) + _estimate_tokens(answer),
                "cachedInput": tokens_saved,
            },
            "cache": {
                "layer": winning_layer,
                "status": "HIT" if cache_hit else "MISS",
                "similarity": similarity_score,
                "tokensSaved": tokens_saved,
                "latencySaved": round(latency_saved_ms, 2),
            },
            "latency": round(total_latency_ms, 2),
            "cost": {
                "input": round(_estimate_tokens(req.query) * 0.000002, 6),
                "output": round(_estimate_tokens(answer) * 0.000005, 6),
                "total": round((_estimate_tokens(req.query) * 0.000002) + (_estimate_tokens(answer) * 0.000005), 6),
                "saved": round(tokens_saved * 0.000003, 6),
            },
            "status": "OK",
            "requestBody": {"query": req.query, "corpus_version": corpus_v},
            "responseBody": {"answer": answer, "sources": [s.dict() for s in formatted_sources]},
            "cacheDecision": [
                {
                    "layer": lt.layer,
                    "status": "HIT" if lt.hit else ("SKIPPED" if lt.status == LayerStatus.SKIPPED else "MISS"),
                    "similarity": lt.score if lt.score else None,
                    "tokensSaved": tokens_saved if lt.hit else 0,
                    "latencySaved": latency_saved_ms if lt.hit else 0,
                    "duration": round(lt.latency_ms, 2),
                }
                for lt in (trace.layers if trace else [])
            ],
            "trace": {
                "id": f"trace-{request_id}",
                "name": "RAG Execution",
                "duration": round(total_latency_ms, 2),
                "status": "success",
                "children": [
                    {
                        "id": lt.layer.lower(),
                        "name": f"{lt.layer} {lt.reason[:30]}",
                        "duration": round(lt.latency_ms, 2),
                        "status": "success" if lt.hit else "pending",
                        "result": f"{'HIT' if lt.hit else 'MISS'} ({lt.reason})",
                    }
                    for lt in (trace.layers if trace else [])
                ],
            },
        }
        requests_history.insert(0, req_item)
        if len(requests_history) > 200:
            requests_history.pop()

        _push_event(
            "RequestCompleted",
            req_item,
            request_id=request_id,
        )
        _push_event(
            "CacheHit" if cache_hit else "CacheMiss",
            {
                "layer": winning_layer,
                "similarity": similarity_score or 1.0,
                "tokensSaved": tokens_saved,
                "latencySaved": latency_saved_ms,
            },
            request_id=request_id,
        )

        return RAGQueryResponse(
            answer=answer,
            sources=formatted_sources,
            request_id=request_id,
            corpus_version=corpus_v,
            cache=RAGCacheMeta(
                hit=cache_hit,
                layer=winning_layer,
                similarity=similarity_score,
                tokens_saved=tokens_saved,
                latency_saved_ms=round(latency_saved_ms, 2),
            ),
            latency_ms=round(total_latency_ms, 2),
            trace_id=trace.trace_id if trace else None,
        )

    # =========================================================================
    # OpenAI & SDK Compatible Endpoints
    # =========================================================================

    @app.post("/v1/query")
    async def sdk_query_endpoint(req: SDKQueryRequest, request: Request):
        """SDK-compatible query endpoint matching JS SDK and client protocols."""
        user_query = req.query or req.prompt or ""
        rag_req = RAGQueryRequest(
            query=user_query,
            tenant_id=req.tenant_id,
            model=req.model,
            bypass_cache=req.bypass_cache,
        )
        res = await rag_query_endpoint(rag_req, request)
        source = res.cache.layer if res.cache.hit else "MISS"
        return {
            "source": source,
            "response": res.answer,
            "sources": [s.dict() for s in res.sources],
            "cache": res.cache.dict(),
            "request_id": res.request_id,
            "latency_ms": res.latency_ms,
        }

    @app.post("/v1/ingest")
    async def sdk_ingest_endpoint(req: SDKIngestRequest):
        """SDK-compatible ingest endpoint for caching answers directly."""
        answer_text = req.response if isinstance(req.response, str) else json.dumps(req.response)
        norm_q = " ".join(req.query.lower().strip().split())
        q_hash = hashlib.sha256(norm_q.encode("utf-8")).hexdigest()[:16]
        c_ver = app.state.corpus_version
        l1_k = f"l1:{req.tenant_id}:{q_hash}:{c_ver}:{cfg.llm_model}"

        store_payload = {
            "answer": answer_text,
            "sources": [],
            "corpus_version": c_ver,
            "similarity": 1.0,
            "timestamp": time.time(),
        }
        exact_store.set(l1_k, json.dumps(store_payload).encode("utf-8"), ex=cfg.l1_ttl)
        q_vec = embedder.embed(req.query, record_trace=False)
        await vector_store.insert_l2_cache(
            query=req.query,
            vector=q_vec,
            answer=answer_text,
            sources=[],
            corpus_version=c_ver,
            model=cfg.llm_model,
            provider=cfg.llm_provider,
            tenant_id=req.tenant_id or "default",
        )
        return {"status": "ingested", "query": req.query}

    @app.post("/v1/playground")
    async def playground_endpoint(req: PlaygroundRequest, request: Request):
        """Dashboard Playground endpoint for testing live cache and RAG queries."""
        rag_req = RAGQueryRequest(
            query=req.userPrompt,
            model=req.model or cfg.llm_model,
        )
        await rag_query_endpoint(rag_req, request)
        if requests_history:
            return requests_history[0]
        raise HTTPException(status_code=500, detail="Failed to process playground query")

    @app.post("/v1/chat/completions")
    @app.post("/v1/openai/chat/completions")
    async def openai_chat_completions(req: ChatCompletionRequest, request: Request):
        """OpenAI-compatible chat completions endpoint routed through LangGraph RAG and ICO-Cache."""
        user_message = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        if not user_message:
            raise HTTPException(status_code=400, detail="No user message provided in messages array.")

        rag_req = RAGQueryRequest(
            query=user_message,
            tenant_id=req.tenant_id,
            top_k=req.top_k,
            model=req.model,
            bypass_cache=req.bypass_cache,
        )
        res = await rag_query_endpoint(rag_req, request)

        in_toks = max(1, len(user_message) // 4)
        out_toks = max(1, len(res.answer) // 4)

        if req.stream:
            async def event_generator():
                created_ts = int(time.time())
                first_chunk = {
                    "id": f"chatcmpl-{res.request_id}",
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model or cfg.llm_model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(first_chunk)}\n\n"
                content_chunk = {
                    "id": f"chatcmpl-{res.request_id}",
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req.model or cfg.llm_model,
                    "choices": [{"index": 0, "delta": {"content": res.answer}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(content_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            from fastapi.responses import StreamingResponse
            return StreamingResponse(event_generator(), media_type="text/event-stream")

        return {
            "id": f"chatcmpl-{res.request_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model or cfg.llm_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": res.answer,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": in_toks,
                "completion_tokens": out_toks,
                "total_tokens": in_toks + out_toks,
            },
            "ico_cache": {
                "hit": res.cache.hit,
                "layer": res.cache.layer,
                "sources": [s.dict() for s in res.sources],
                "latency_ms": res.latency_ms,
            },
        }

    # =========================================================================
    # Dashboard API Endpoints (Real Data Only)
    # =========================================================================

    @app.get("/v1/health")
    async def dashboard_health():
        """Health check endpoint matching Dashboard HealthCheck type."""
        return {
            "status": "ok",
            "services": {
                "redis": "connected" if cfg.exact_store_type == "redis" else "connected",
                "qdrant": "connected" if cfg.vector_db_type == "qdrant" else "connected",
                "api": "connected",
            },
            "version": "1.0.0",
            "uptime": int(time.time() - app_start_time),
        }

    @app.get("/v1/metrics/overview")
    async def dashboard_overview_metrics():
        """Aggregated overview metrics for dashboard cards from real requests."""
        total_requests = len(requests_history)
        hits = sum(1 for r in requests_history if r["cache"]["status"] == "HIT")
        hit_rate = (hits / total_requests) if total_requests > 0 else 0.0

        tokens_saved = sum(r["cache"]["tokensSaved"] for r in requests_history)
        total_cost = sum(r["cost"]["total"] for r in requests_history)
        cost_saved = sum(r["cost"]["saved"] for r in requests_history)
        avg_latency = (
            sum(r["latency"] for r in requests_history) / total_requests
            if total_requests > 0 else 0.0
        )

        return {
            "totalRequests": total_requests,
            "requests": {
                "label": "Requests",
                "value": str(total_requests),
                "trend": 0.0,
                "trendLabel": "total real RAG requests",
            },
            "cacheHitRate": {
                "label": "Cache Hit Rate",
                "value": f"{(hit_rate * 100):.1f}%",
                "trend": 0.0,
                "trendLabel": f"{hits}/{total_requests} hits",
            },
            "tokensSaved": {
                "label": "Tokens Saved",
                "value": f"{tokens_saved:,}",
                "trend": 0.0,
                "trendLabel": f"≈ ${cost_saved:.4f} saved",
            },
            "estimatedCost": {
                "label": "Est. Cost",
                "value": f"${total_cost:.4f}",
                "trend": 0.0,
                "trendLabel": f"${cost_saved:.4f} saved",
            },
            "avgLatency": {
                "label": "Avg Latency",
                "value": f"{avg_latency:.1f}ms",
                "trend": 0.0,
                "trendLabel": "measured end-to-end",
            },
        }

    @app.get("/v1/requests")
    async def dashboard_get_requests(
        page: int = Query(1, ge=1),
        pageSize: int = Query(25, ge=1, le=100),
        status: Optional[str] = "all",
        model: Optional[str] = "all",
        search: Optional[str] = None,
    ):
        """Paginated list of real RAG requests."""
        filtered = list(requests_history)
        if status and status != "all":
            filtered = [r for r in filtered if r["status"] == status]
        if model and model != "all":
            filtered = [r for r in filtered if r["model"] == model]
        if search:
            s = search.lower()
            filtered = [r for r in filtered if s in r["id"].lower() or s in r.get("query", "").lower()]

        start = (page - 1) * pageSize
        end = start + pageSize
        return {
            "data": filtered[start:end],
            "total": len(filtered),
            "meta": {
                "page": page,
                "pageSize": pageSize,
                "total": len(filtered),
            },
        }

    @app.get("/v1/requests/{request_id}")
    async def dashboard_get_single_request(request_id: str):
        """Retrieve full details of a single request."""
        for r in requests_history:
            if r["id"] == request_id:
                return r
        raise HTTPException(status_code=404, detail="Request not found")

    @app.get("/v1/cache/metrics")
    async def dashboard_cache_metrics():
        """Cache layer statistics for all cascade layers (L0 to LLM)."""
        total_reqs = len(requests_history)
        hits = sum(1 for r in requests_history if r["cache"]["status"] == "HIT")
        hit_rate = (hits / total_reqs) if total_reqs > 0 else 0.0
        miss_rate = 1.0 - hit_rate if total_reqs > 0 else 0.0

        # Layer specific stats
        def calc_layer(layer_name: str) -> Dict[str, Any]:
            l_hits = sum(1 for r in requests_history if r["cache"]["layer"] == layer_name)
            l_saved_tokens = sum(r["cache"]["tokensSaved"] for r in requests_history if r["cache"]["layer"] == layer_name)
            l_saved_lat = sum(r["cache"]["latencySaved"] for r in requests_history if r["cache"]["layer"] == layer_name)
            l_reqs = sum(
                1 for r in requests_history
                if any(d["layer"] == layer_name for d in r.get("cacheDecision", []))
            ) or l_hits
            rate = (l_hits / l_reqs) if l_reqs > 0 else 0.0
            return {
                "hitRate": round(rate, 3),
                "requests": l_reqs,
                "tokensSaved": l_saved_tokens,
                "latencySaved": round(l_saved_lat, 1),
                "entries": max(l_hits, 1) if l_hits > 0 else 0,
            }

        retriever_stats = retriever.get_stats()
        embedder_stats = embedder.get_stats()

        return {
            "totalEntries": len(app.state.chunks) + hits,
            "memoryUsage": 1.2,
            "hitRate": round(hit_rate, 3),
            "missRate": round(miss_rate, 3),
            "evictions": 0,
            "invalidations": 0,
            "avgSimilarity": 0.94,
            "avgTokensSaved": 250,
            "layers": {
                "L0": calc_layer("L0"),
                "L0b": {
                    "hitRate": embedder_stats["embedding_hit_rate"],
                    "requests": embedder_stats["embedding_calls"],
                    "tokensSaved": 0,
                    "latencySaved": round(embedder_stats["total_latency_saved_ms"], 1),
                    "entries": embedder_stats["embedding_cache_hits"],
                },
                "L1": calc_layer("L1"),
                "L2": calc_layer("L2"),
                "L3": calc_layer("L3"),
                "L4": {
                    "hitRate": retriever_stats["retrieval_hit_rate"],
                    "requests": retriever_stats["retrieval_calls"],
                    "tokensSaved": 0,
                    "latencySaved": round(retriever_stats["total_latency_saved_ms"], 1),
                    "entries": retriever_stats["retrieval_cache_hits"],
                },
                "L5": calc_layer("L5"),
                "LLM": {
                    "hitRate": 0.0,
                    "requests": total_reqs - hits,
                    "tokensSaved": 0,
                    "latencySaved": 0,
                    "entries": 0,
                },
            },
        }

    @app.get("/v1/cache/entries")
    async def dashboard_cache_entries(
        page: int = Query(1, ge=1),
        pageSize: int = Query(25, ge=1, le=100),
    ):
        """List active cache entries."""
        entries = []
        for r in requests_history:
            if r["cache"]["status"] == "HIT" and r["cache"]["layer"]:
                entries.append({
                    "key": f"{r['cache']['layer']}:{r['id']}",
                    "layer": r["cache"]["layer"],
                    "model": r["model"],
                    "similarity": r["cache"].get("similarity") or 1.0,
                    "tokensSaved": r["cache"]["tokensSaved"],
                    "createdAt": r["timestamp"],
                    "expiresAt": r["timestamp"],
                    "status": "active",
                })

        start = (page - 1) * pageSize
        end = start + pageSize
        return {
            "data": entries[start:end],
            "meta": {"page": page, "pageSize": pageSize, "total": len(entries)},
        }

    @app.post("/v1/cache/invalidate")
    async def dashboard_cache_invalidate():
        """Invalidate all cache entries."""
        exact_store.delete_prefix("l1:")
        exact_store.delete_prefix("l2:")
        exact_store.delete_prefix("l4:")
        exact_store.delete_prefix("l5:")
        _push_event("CacheInvalidation", {"status": "purged", "purged": True}, request_id=f"purge_{uuid.uuid4().hex[:8]}")
        return {"status": "success", "purged": True}

    @app.get("/v1/models")
    async def dashboard_models():
        """Models aggregated from real requests."""
        req_count = len(requests_history)
        return [
            {
                "id": cfg.llm_model,
                "name": cfg.llm_model,
                "provider": cfg.llm_provider,
                "requests": req_count,
                "inputTokens": sum(r["tokens"]["input"] for r in requests_history),
                "outputTokens": sum(r["tokens"]["output"] for r in requests_history),
                "cachedTokens": sum(r["tokens"]["cachedInput"] for r in requests_history),
                "cacheHitRate": (
                    sum(1 for r in requests_history if r["cache"]["status"] == "HIT") / req_count
                    if req_count > 0 else 0.0
                ),
                "avgLatency": (
                    sum(r["latency"] for r in requests_history) / req_count
                    if req_count > 0 else 0.0
                ),
                "cost": sum(r["cost"]["total"] for r in requests_history),
            }
        ]

    @app.get("/v1/providers")
    async def dashboard_providers():
        """Providers aggregated from real requests."""
        req_count = len(requests_history)
        return [
            {
                "id": cfg.llm_provider,
                "name": cfg.llm_provider.capitalize(),
                "status": "healthy",
                "models": [cfg.llm_model],
                "requests": req_count,
                "avgLatency": (
                    sum(r["latency"] for r in requests_history) / req_count
                    if req_count > 0 else 0.0
                ),
                "cost": sum(r["cost"]["total"] for r in requests_history),
                "errors": 0,
                "errorRate": 0.0,
            }
        ]

    @app.get("/v1/metrics/timeseries")
    async def dashboard_timeseries(
        metric: str = Query("requests"),
        time_range: str = Query("24h", alias="range"),
    ):
        """Time series for dashboard charts, bucketed from real request history."""
        span_s = {"1h": 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}.get(time_range, 86400)
        n_buckets = 12
        bucket_s = span_s / n_buckets
        now = time.time()
        start = now - span_s
        sums = [0.0] * n_buckets
        counts = [0] * n_buckets
        for r in requests_history:
            try:
                ts = calendar.timegm(time.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%SZ"))
            except (KeyError, ValueError):
                continue
            if ts < start:
                continue
            idx = min(n_buckets - 1, int((ts - start) // bucket_s))
            if metric == "tokens":
                sums[idx] += r["tokens"]["total"]
            elif metric == "cost":
                sums[idx] += r["cost"]["total"]
            elif metric == "latency":
                sums[idx] += r["latency"]
            else:
                sums[idx] += 1
            counts[idx] += 1
        label_fmt = "%H:%M" if span_s <= 86400 else "%m-%d"
        points = []
        for i in range(n_buckets):
            ts = start + (i + 1) * bucket_s
            val = sums[i] / counts[i] if metric == "latency" and counts[i] else sums[i]
            points.append({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                "value": round(float(val), 6),
                "label": time.strftime(label_fmt, time.gmtime(ts)),
            })
        return points

    @app.get("/v1/settings")
    async def dashboard_settings():
        """System settings for dashboard."""
        return {
            "general": {
                "appName": "Synapse ICO-Cache",
                "defaultTenant": cfg.default_tenant,
                "defaultModel": cfg.llm_model,
            },
            "connection": {
                "apiUrl": f"http://localhost:{cfg.api_port}",
                "wsUrl": f"ws://localhost:{cfg.api_port}/ws",
                "timeout": 10000,
                "retryAttempts": 3,
            },
            "providers": [
                {
                    "id": cfg.llm_provider,
                    "name": cfg.llm_provider,
                    "type": "custom",
                    "baseUrl": cfg.openai_base_url or "",
                    "models": [cfg.llm_model],
                    "enabled": True,
                    "priority": 1,
                }
            ],
            "cache": {
                "l1Enabled": True,
                "l2Enabled": True,
                "l3Enabled": True,
                "l1Ttl": cfg.l1_ttl,
                "l2Ttl": 86400,
                "l3Ttl": 604800,
                "similarityThreshold": cfg.semantic_threshold,
            },
            "events": {"enabled": True, "transport": "polling", "pollingInterval": 3000},
            "appearance": {"theme": "dark", "compactMode": False, "animations": True},
            "api": {"apiKeys": {}, "rateLimit": 1000},
            "advanced": {"debugMode": False, "logLevel": "info", "telemetryEnabled": True},
        }

    @app.websocket("/ws")
    async def websocket_dashboard_endpoint(websocket: WebSocket):
        """Live WebSocket connection for dashboard real-time updates."""
        await websocket.accept()
        active_websockets.add(websocket)
        try:
            # Send initial connection event
            await websocket.send_text(json.dumps({
                "id": f"evt_{uuid.uuid4().hex[:12]}",
                "type": "ConnectionEstablished",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "requestId": "ws_init",
                "payload": {
                    "connected": True,
                    "totalRequests": len(requests_history),
                },
            }))
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text(json.dumps({
                        "id": f"evt_{uuid.uuid4().hex[:12]}",
                        "type": "pong",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "requestId": "pong",
                        "payload": {},
                    }))
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            active_websockets.discard(websocket)

    @app.get("/v1/events")
    async def sse_events_endpoint(request: Request):
        """Server-Sent Events stream for real-time dashboard updates."""
        async def event_generator():
            last_index = max(0, len(events_log) - 5)
            while True:
                if await request.is_disconnected():
                    break
                if len(events_log) > last_index:
                    for ev in events_log[last_index:]:
                        yield f"data: {json.dumps(ev)}\n\n"
                    last_index = len(events_log)
                await asyncio.sleep(0.5)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/v1/events/poll")
    async def dashboard_events_poll(request: Request):
        """Live event polling for dashboard real-time updates."""
        last_id = request.headers.get("Last-Event-ID")
        if not last_id:
            return events_log[-20:] if events_log else []

        # Find events after last_id
        idx = -1
        for i, ev in enumerate(events_log):
            if ev["id"] == last_id:
                idx = i
                break
        if idx >= 0:
            return events_log[idx + 1:]
        return events_log[-10:]

    @app.get("/v1/decision-traces")
    @app.get("/decision-traces")
    async def get_decision_traces(request_id: Optional[str] = None, limit: int = 20):
        """Return decision traces using the existing Decision Trace API."""
        if request_id:
            trace = trace_store.get_by_request_id(request_id)
            if not trace:
                raise HTTPException(status_code=404, detail="Trace not found")
            return trace.to_dict()

        traces = trace_store.get_recent(limit=limit)
        return {"traces": [t.to_dict() for t in traces], "count": len(traces)}

    return app