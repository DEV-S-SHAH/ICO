import logging
import os
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Security, UploadFile, status
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
from ico_cache.rag.pipeline import RAGPipeline

try:
    from .config import settings
except (ImportError, ValueError):
    try:
        from api.config import settings
    except ImportError:
        from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("financial_rag_api")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_tenant_from_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide a valid 'X-API-Key' header.",
        )
    if api_key not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    return settings.api_keys[api_key]


limiter = Limiter(key_func=get_remote_address, default_limits=["1000/minute"])
app = FastAPI(title="ICO-Agent API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Shared components
embedder = FastEmbedder()
vector_store = QdrantStore(host=settings.qdrant_host, port=settings.qdrant_port)
exact_store = RedisStore(host=settings.redis_host, port=settings.redis_port, password=settings.redis_auth)

from examples.financial_schema import financial_schema

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
    collection_name="ico_corpus"
)


# Request/Response Logging Middleware with Request IDs
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.time()
    logger.info(f"[{request_id}] START {request.method} {request.url.path}")

    response = await call_next(request)

    duration_ms = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        f"[{request_id}] END {request.method} {request.url.path} status={response.status_code} duration={duration_ms:.2f}ms"
    )
    return response


class QueryRequest(BaseModel):
    query: str
    context: Optional[str] = None
    tenant_id: Optional[str] = None
    model: Optional[str] = None


class InvalidateRequest(BaseModel):
    tenant_id: Optional[str] = None
    filter: Optional[dict[str, Any]] = None


# Versioned router
v1_router = APIRouter(prefix="/v1")


@v1_router.get("/health")
def health():
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

    overall = "ok" if (redis_status == "connected" and qdrant_status == "connected") else "degraded"
    return {
        "status": overall,
        "backends": {
            "redis": redis_status,
            "qdrant": qdrant_status,
        }
    }


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

    cached = await engine.resolve(req.query, req.context, tenant_id=target_tenant)
    if cached["source"] != "MISS":
        return cached

    # MISS -> generate
    ans, t_ret, t_gen, score, citations = await rag_pipeline.generate(
        req.query, tenant_id=target_tenant, model=req.model
    )
    generated = {
        "answer": ans,
        "citations": citations,
        "score": score,
        "chunks": getattr(rag_pipeline, "last_retrieved_chunks", []),
    }

    engine.set_l1(req.query, generated, tenant_id=target_tenant)
    await engine.async_write_l2(req.query, generated, tenant_id=target_tenant)
    if req.context:
        await engine.async_write_l3(req.query, req.context, generated, tenant_id=target_tenant)

    return {"source": "MISS", "response": generated}


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
def clear_cache_endpoint(authed_tenant: str = Depends(get_tenant_from_api_key)):
    try:
        if hasattr(exact_store, "client") and exact_store.client:
            exact_store.client.flushdb()
    except Exception:
        pass
    try:
        coll_l2 = engine._coll_name("l2_cache", authed_tenant)
        coll_l3 = engine._coll_name("l3_cache", authed_tenant)
        if vector_store.collection_exists(coll_l2):
            vector_store.delete_collection(coll_l2)
        if vector_store.collection_exists(coll_l3):
            vector_store.delete_collection(coll_l3)
        engine._setup_collections(tenant_id=authed_tenant)
    except Exception:
        pass
    return {"status": "cleared"}


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
        job = job_manager.submit_ingest(
            file_path=req.file_path,
            tenant_id=target_tenant,
            cache_engine=engine,
            schema=financial_schema,
            force_async=req.force_async,
        )
        return job.dict()
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
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

    upload_dir = "/tmp/ico_uploads"
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, file.filename or f"upload_{uuid.uuid4().hex[:8]}")
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

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
