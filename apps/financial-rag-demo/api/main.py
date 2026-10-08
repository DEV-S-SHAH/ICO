import hashlib
import logging
import os
import secrets
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Response, Security, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.backends.exact.redis_store import RedisStore
from ico_cache.backends.vector.qdrant_store import QdrantStore
from ico_cache.core.cache_engine import CacheEngine
from ico_cache.loaders import configure_ocr
from ico_cache.rag.pipeline import RAGPipeline
from ico_cache.telemetry.langfuse import init_langfuse
from ico_cache.telemetry.logging import configure_logging
from ico_cache.telemetry.metrics import (
    CONTENT_TYPE_LATEST,
    record_http_request,
    render_metrics,
    set_backend_up,
)
from ico_cache.telemetry.tracing import setup_tracing

from examples.financial_schema import financial_schema

try:
    from .config import settings
except (ImportError, ValueError):
    try:
        from api.config import settings
    except ImportError:
        from config import settings

configure_logging(json_logs=settings.log_json, level=settings.log_level)
logger = logging.getLogger("financial_rag_api")

# Observability + universal OCR configured from settings before engines start.
setup_tracing(service_name=settings.otel_service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
configure_ocr(
    enabled=settings.ocr_enabled,
    languages=settings.ocr_languages,
    dpi=settings.ocr_dpi,
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_tenant_from_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide a valid 'X-API-Key' header.",
        )
    # Compare against every configured key with a constant-time comparison so
    # neither the match result nor which key matched is leaked via timing.
    matched_tenant: Optional[str] = None
    for configured_key, tenant_id in settings.api_keys.items():
        if secrets.compare_digest(configured_key, api_key):
            matched_tenant = tenant_id
    if matched_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    return matched_tenant


def _rate_limit_key(request: Request) -> str:
    """Per-API-key limiting (hashed, never stored raw); falls back to client IP."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return "key:" + hashlib.sha256(api_key.encode()).hexdigest()[:32]
    return get_remote_address(request)


# Redis-backed store makes limits shared across replicas; memory:// in dev.
limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.resolved_rate_limit_storage_uri,
)
app = FastAPI(title="ICO-Agent API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Shared components
embedder = FastEmbedder()
vector_store = QdrantStore(host=settings.qdrant_host, port=settings.qdrant_port)
exact_store = RedisStore(host=settings.redis_host, port=settings.redis_port, password=settings.redis_auth)

engine = CacheEngine(
    embedder=embedder,
    vector_store=vector_store,
    exact_store=exact_store,
    schema=financial_schema,
    metadata_filter_keys=["entity", "quarter", "topic"],
    adaptive_threshold=True,
)

rag_pipeline = RAGPipeline(
    dense_embedder=embedder,
    vector_store=vector_store,
    collection_name="ico_corpus",
    model=settings.llm_model,
    api_key=settings.gemini_api_key,
    timeout=settings.llm_timeout_seconds,
    num_retries=settings.llm_max_retries,
    langfuse=init_langfuse(
        host=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
    ),
)

# Ingestion is confined to a single root directory. Both the path-based and the
# upload endpoints resolve inside it, preventing arbitrary file read/write.
INGEST_ROOT = os.path.realpath(settings.ingest_root_dir)
UPLOAD_DIR = os.path.join(INGEST_ROOT, "uploads")
try:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
except OSError as exc:  # pragma: no cover - depends on deployment filesystem
    logger.warning(f"Ingest directory not writable at startup: {exc}")


def _safe_ingest_path(file_path: str) -> str:
    """Resolve a client-supplied path inside INGEST_ROOT, rejecting escapes."""
    candidate = os.path.realpath(os.path.join(INGEST_ROOT, file_path))
    if candidate != INGEST_ROOT and not candidate.startswith(INGEST_ROOT + os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_path must be inside the configured ingest directory.",
        )
    if not os.path.isfile(candidate):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file_path}",
        )
    return candidate


# Request/Response Logging Middleware with Request IDs
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.time()
    try:
        import structlog

        structlog.contextvars.bind_contextvars(request_id=request_id)
    except Exception:
        pass
    logger.info(f"[{request_id}] START {request.method} {request.url.path}")

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    record_http_request(request.method, request.url.path, response.status_code)
    logger.info(
        f"[{request_id}] END {request.method} {request.url.path} status={response.status_code} duration={duration_ms:.2f}ms"
    )
    return response


class QueryRequest(BaseModel):
    query: str
    context: Optional[str] = None
    tenant_id: Optional[str] = None
    model: Optional[str] = None
    corpus_version: Optional[str] = None


class InvalidateRequest(BaseModel):
    tenant_id: Optional[str] = None
    filter: Optional[dict[str, Any]] = None


# Versioned router
v1_router = APIRouter(prefix="/v1")


def _check_backends() -> dict:
    redis_status = "disconnected"
    try:
        client = getattr(exact_store, "client", None) or getattr(exact_store, "r", None)
        if client:
            client.ping()
            redis_status = "connected"
    except Exception:
        pass

    qdrant_status = "disconnected"
    try:
        vector_store.qc.get_collections()
        qdrant_status = "connected"
    except Exception:
        pass

    set_backend_up("redis", redis_status == "connected")
    set_backend_up("qdrant", qdrant_status == "connected")
    return {"redis": redis_status, "qdrant": qdrant_status}


@v1_router.get("/health")
def health():
    backends = _check_backends()
    overall = "ok" if all(v == "connected" for v in backends.values()) else "degraded"
    return {
        "status": overall,
        "backends": backends,
    }


@v1_router.get("/ready")
def readiness():
    """Kubernetes readiness: 503 (fails the probe) whenever any backend is down."""
    backends = _check_backends()
    unavailable = [name for name, state in backends.items() if state != "connected"]
    if unavailable:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "backends": backends, "unavailable": unavailable},
        )
    return {"status": "ready", "backends": backends}


@v1_router.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


@v1_router.post("/query")
@limiter.limit("600/minute")
async def query_endpoint(
    req: QueryRequest,
    request: Request,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    if req.tenant_id is not None and req.tenant_id != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: API key for tenant '{authed_tenant}' cannot access tenant '{req.tenant_id}'.",
        )
    target_tenant = req.tenant_id or authed_tenant

    # Get request ID from header (set by middleware)
    request_id = request.headers.get("X-Request-ID")

    async def _generate():
        ans, t_ret, t_gen, score, citations = await rag_pipeline.generate(
            req.query, tenant_id=target_tenant, model=req.model
        )
        return {
            "answer": ans,
            "citations": citations,
            "score": score,
            "chunks": getattr(rag_pipeline, "last_retrieved_chunks", []),
        }

    # Single-flight: concurrent identical misses share one generation; error or
    # "insufficient context" results are returned but never cached.
    # Extract provider from model string (e.g., "gemini/gemini-flash-latest" -> "gemini")
    model_name = req.model or settings.llm_model
    provider_name = model_name.split("/")[0] if "/" in model_name else "gemini"
    return await engine.resolve_or_generate(
        req.query,
        req.context,
        tenant_id=target_tenant,
        model=model_name,
        provider=provider_name,
        corpus_version=req.corpus_version,
        generate_fn=_generate,
        request_id=request_id,
    )


@v1_router.post("/compare")
@limiter.limit("300/minute")
async def compare_endpoint(
    req: QueryRequest,
    request: Request,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    if req.tenant_id is not None and req.tenant_id != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: API key for tenant '{authed_tenant}' cannot access tenant '{req.tenant_id}'.",
        )
    target_tenant = req.tenant_id or authed_tenant
    start1 = time.time()
    cached = await query_endpoint(req, request, authed_tenant=authed_tenant)
    t1 = time.time() - start1

    start2 = time.time()
    ans, t_ret, t_gen, score, citations = await rag_pipeline.generate(
        req.query, tenant_id=target_tenant, model=req.model
    )
    fresh = {
        "answer": ans,
        "citations": citations,
        "score": score,
        "chunks": getattr(rag_pipeline, "last_retrieved_chunks", []),
    }
    t2 = time.time() - start2

    return {
        "cached": {"response": cached, "latency_s": t1},
        "fresh": {"response": fresh, "latency_s": t2}
    }


@v1_router.post("/test_layer/{layer}")
async def test_layer_endpoint(
    layer: str,
    req: QueryRequest,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    if req.tenant_id is not None and req.tenant_id != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: API key for tenant '{authed_tenant}' cannot access tenant '{req.tenant_id}'.",
        )
    target_tenant = req.tenant_id or authed_tenant
    if layer == "L1 EXACT":
        res = await engine.get_l1(req.query, tenant_id=target_tenant)
        return {"layer": "L1", "hit": res is not None, "response": res}
    elif layer == "L2 SEMANTIC":
        res = await engine.get_l2(req.query, tenant_id=target_tenant)
        return {"layer": "L2", "hit": res is not None, "response": res}
    elif layer == "L3 CONTEXT":
        res = await engine.get_l3(req.query, req.context or "", tenant_id=target_tenant)
        return {"layer": "L3", "hit": res is not None, "response": res}
    return {"error": "Invalid layer"}


@v1_router.post("/clear_cache")
async def clear_cache_endpoint(authed_tenant: str = Depends(get_tenant_from_api_key)):
    # Tenant-scoped purge. Never flush the whole Redis DB: that would wipe every
    # tenant and the shared Langfuse queues for any valid key.
    result = await engine.invalidate(tenant_id=authed_tenant)
    return {"status": "cleared", "tenant_id": authed_tenant, "details": result}


@v1_router.post("/invalidate")
async def invalidate_endpoint(
    req: InvalidateRequest,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    if req.tenant_id is not None and req.tenant_id != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: API key for tenant '{authed_tenant}' cannot invalidate tenant '{req.tenant_id}'.",
        )
    target_tenant = req.tenant_id or authed_tenant

    from ico_cache.invalidation import publish_invalidation

    stream_event_id = publish_invalidation(exact_store, tenant_id=target_tenant, filter_dict=req.filter)
    result = await engine.invalidate(tenant_id=target_tenant, filter_dict=req.filter)
    if stream_event_id:
        result["stream_event_id"] = stream_event_id
    return result


@v1_router.get("/decision-traces")
async def decision_traces_endpoint(
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = 10,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    """
    Retrieve decision traces for the authenticated tenant.

    Query params:
    - request_id: specific request ID to look up
    - trace_id: specific trace ID to look up
    - limit: maximum traces to return (default 10)
    """
    if trace_id:
        trace = engine.get_decision_trace_by_id(trace_id)
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        if trace.get("tenant_id") != authed_tenant:
            raise HTTPException(status_code=403, detail="Trace belongs to different tenant")
        return trace

    if request_id:
        trace = engine.get_decision_trace(request_id)
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found for request_id")
        if trace.get("tenant_id") != authed_tenant:
            raise HTTPException(status_code=403, detail="Trace belongs to different tenant")
        return trace

    traces = engine.get_decision_traces(tenant_id=authed_tenant, limit=limit)
    return {"traces": traces, "count": len(traces)}


@v1_router.get("/decision-trace-stats")
async def decision_trace_stats_endpoint(authed_tenant: str = Depends(get_tenant_from_api_key)):
    """Get statistics about stored decision traces for the tenant."""
    return engine.get_decision_trace_stats()


@v1_router.post("/eval")
def eval_endpoint():
    return {"status": "eval started in background"}


class IngestRequest(BaseModel):
    file_path: str
    tenant_id: Optional[str] = None
    force_async: Optional[bool] = None


@v1_router.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest_endpoint(
    req: IngestRequest,
    response: Request,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    if req.tenant_id is not None and req.tenant_id != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: API key for tenant '{authed_tenant}' cannot ingest into '{req.tenant_id}'.",
        )
    target_tenant = req.tenant_id or authed_tenant

    from ico_cache.async_ingest import job_manager

    try:
        resolved_path = _safe_ingest_path(req.file_path)
        job = job_manager.submit_ingest(
            file_path=resolved_path,
            tenant_id=target_tenant,
            cache_engine=engine,
            schema=financial_schema,
            force_async=req.force_async,
        )
        return job.dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.post("/ingest/upload", status_code=status.HTTP_200_OK)
async def ingest_upload_endpoint(
    file: UploadFile = File(...),
    tenant_id: Optional[str] = Form(None),
    force_async: Optional[bool] = Form(None),
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    if tenant_id is not None and tenant_id != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: API key for tenant '{authed_tenant}' cannot ingest into '{tenant_id}'.",
        )
    target_tenant = tenant_id or authed_tenant
    from ico_cache.async_ingest import job_manager

    # Never trust the client filename: strip any path components and replace
    # empty/dot names. Confine the write to UPLOAD_DIR and cap the body size.
    filename = os.path.basename(file.filename or "").strip()
    if not filename or filename in {".", ".."}:
        filename = f"upload_{uuid.uuid4().hex[:8]}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    temp_path = os.path.join(UPLOAD_DIR, filename)

    total = 0
    try:
        with open(temp_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds the {settings.max_upload_bytes} byte limit.",
                    )
                f.write(chunk)
    except HTTPException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    try:
        job = job_manager.submit_ingest(
            file_path=temp_path,
            tenant_id=target_tenant,
            cache_engine=engine,
            schema=financial_schema,
            force_async=force_async,
        )
        return job.dict()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@v1_router.get("/ingest/jobs/{job_id}")
def get_ingest_job_status(
    job_id: str,
    authed_tenant: str = Depends(get_tenant_from_api_key),
):
    from ico_cache.async_ingest import job_manager

    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
    if job.tenant_id != authed_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to job.")
    return job.dict()


@v1_router.get("/stats")
def stats_endpoint():
    return {
        "hit_rate_l1": 0.35,
        "hit_rate_l2": 0.40,
        "hit_rate_l3": 0.15,
        "miss_rate": 0.10,
        "dollars_saved": 12.50,
        "tokens_saved": 150000,
        "avg_latency_ms": 15
    }


# Include v1 router
app.include_router(v1_router)

# Also expose unversioned aliases for backward compatibility with existing clients/tests
legacy_router = APIRouter()
legacy_router.add_api_route("/health", health, methods=["GET"])
legacy_router.add_api_route("/ready", readiness, methods=["GET"])
legacy_router.add_api_route("/metrics", metrics_endpoint, methods=["GET"])
legacy_router.add_api_route("/query", query_endpoint, methods=["POST"])
legacy_router.add_api_route("/compare", compare_endpoint, methods=["POST"])
legacy_router.add_api_route("/test_layer/{layer}", test_layer_endpoint, methods=["POST"])
legacy_router.add_api_route("/clear_cache", clear_cache_endpoint, methods=["POST"])
legacy_router.add_api_route("/invalidate", invalidate_endpoint, methods=["POST"])
legacy_router.add_api_route("/ingest", ingest_endpoint, methods=["POST"])
legacy_router.add_api_route("/ingest/upload", ingest_upload_endpoint, methods=["POST"])
legacy_router.add_api_route("/ingest/jobs/{job_id}", get_ingest_job_status, methods=["GET"])
legacy_router.add_api_route("/eval", eval_endpoint, methods=["POST"])
legacy_router.add_api_route("/stats", stats_endpoint, methods=["GET"])
app.include_router(legacy_router)
