"""FastAPI application for OpenAI-compatible gateway."""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
from ico_cache.backends.exact.redis_store import RedisStore
from ico_cache.backends.vector.qdrant_store import QdrantStore
from ico_cache.core.cache_engine import CacheEngine
from ico_cache.telemetry.logging import configure_logging
from ico_cache.telemetry.tracing import setup_tracing

from .config import GatewayConfig
from .providers import AnthropicProvider, OpenAIProvider, ProviderRegistry

logger = structlog.get_logger("ico_cache.gateway.app")


class ChatCompletionMessage(BaseModel):
    """OpenAI chat message."""

    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI chat completion request."""

    model: str
    messages: List[ChatCompletionMessage]
    temperature: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1)
    stream: Optional[bool] = False
    stop: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    user: Optional[str] = None


def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = GatewayConfig.from_env()

    # Configure observability
    configure_logging(json_logs=config.log_json, level=config.log_level)
    setup_tracing(
        service_name=config.otel_service_name,
        otlp_endpoint=config.otel_exporter_otlp_endpoint,
    )

    app = FastAPI(
        title="ICO-Cache OpenAI Gateway",
        version="1.0.0",
        description="OpenAI-compatible gateway with ICO-Cache integration",
    )

    # Initialize ICO-Cache components
    embedder = FastEmbedder()
    vector_store = QdrantStore(host=config.qdrant_host, port=config.qdrant_port)
    exact_store = RedisStore(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password,
    )

    cache_engine = CacheEngine(
        embedder=embedder,
        vector_store=vector_store,
        exact_store=exact_store,
        schema=None,  # Generic gateway, no schema enforcement
        thresh_semantic=config.semantic_threshold,
        adaptive_threshold=config.adaptive_threshold,
        target_hit_rate=config.target_hit_rate,
    )

    # Initialize provider registry
    provider_registry = ProviderRegistry()

    # Register providers from config
    for provider_name, provider_config in config.providers.items():
        if provider_name == "openai":
            provider = OpenAIProvider(provider_config)
        elif provider_name == "anthropic":
            provider = AnthropicProvider(provider_config)
        elif provider_name == "google":
            # Google uses OpenAI-compatible format through their API
            provider = OpenAIProvider(provider_config)
        else:
            # Default to OpenAI-compatible
            provider = OpenAIProvider(provider_config)

        provider_registry.register(provider_name, provider)

    # Store in app state
    app.state.config = config
    app.state.cache_engine = cache_engine
    app.state.provider_registry = provider_registry
    app.state.embedder = embedder
    app.state.vector_store = vector_store
    app.state.exact_store = exact_store
    app.state.requests_history = []
    app.state.events_log = []
    app.state.start_time = time.time()

    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        """Log all requests with request IDs."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.time()

        try:
            structlog.contextvars.bind_contextvars(request_id=request_id)
        except Exception:
            pass

        logger.info(
            "request_start",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)

        duration_ms = (time.time() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request_end",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )

        return response

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        # Check Redis
        redis_healthy = False
        try:
            client = getattr(exact_store, "client", None) or getattr(exact_store, "r", None)
            if client:
                client.ping()
                redis_healthy = True
        except Exception as e:
            logger.warning("redis_health_check_failed", error=str(e))

        # Check Qdrant
        qdrant_healthy = False
        try:
            vector_store.qc.get_collections()
            qdrant_healthy = True
        except Exception as e:
            logger.warning("qdrant_health_check_failed", error=str(e))

        overall_status = "healthy" if (redis_healthy and qdrant_healthy) else "degraded"

        return {
            "status": overall_status,
            "backends": {
                "redis": "connected" if redis_healthy else "disconnected",
                "qdrant": "connected" if qdrant_healthy else "disconnected",
            },
            "providers": list(provider_registry._providers.keys()),
        }

    def _messages_to_query(messages: List[ChatCompletionMessage]) -> str:
        """Convert messages to a cache query string."""
        # Use the last user message as the primary query
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        # Fallback: concatenate all messages
        return "\n".join(f"{m.role}: {m.content}" for m in messages)

    def _messages_to_context(messages: List[ChatCompletionMessage]) -> str:
        """Convert message history to context string for cache."""
        # Exclude the last user message (that's the query)
        context_messages = []
        for i, msg in enumerate(messages[:-1]):
            context_messages.append(f"{msg.role}: {msg.content}")
        return "\n".join(context_messages) if context_messages else ""

    async def _generate_completion(
        request_data: ChatCompletionRequest,
    ) -> Dict[str, Any]:
        """Generate completion from upstream provider."""
        provider = provider_registry.get(request_data.model)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No provider configured for model: {request_data.model}",
            )

        model_name = provider_registry.get_model_name(request_data.model)

        # Convert messages to dict format
        messages_dict = [msg.model_dump(exclude_none=True) for msg in request_data.messages]

        # Call provider
        kwargs = {}
        if request_data.temperature is not None:
            kwargs["temperature"] = request_data.temperature
        if request_data.max_tokens is not None:
            kwargs["max_tokens"] = request_data.max_tokens
        if request_data.top_p is not None:
            kwargs["top_p"] = request_data.top_p
        if request_data.stop is not None:
            kwargs["stop"] = request_data.stop
        if request_data.presence_penalty is not None:
            kwargs["presence_penalty"] = request_data.presence_penalty
        if request_data.frequency_penalty is not None:
            kwargs["frequency_penalty"] = request_data.frequency_penalty

        return await provider.chat_completion(messages_dict, model_name, **kwargs)

    @app.post("/v1/chat/completions")
    async def chat_completions(request_data: ChatCompletionRequest, request: Request):
        """OpenAI-compatible chat completions endpoint with ICO-Cache integration."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

        logger.info(
            "chat_completion_request",
            request_id=request_id,
            model=request_data.model,
            stream=request_data.stream,
            message_count=len(request_data.messages),
        )

        # Handle streaming separately
        if request_data.stream:
            return await _handle_streaming(request_data, request_id)

        # Non-streaming: use cache
        query = _messages_to_query(request_data.messages)
        context = _messages_to_context(request_data.messages)

        # Extract provider name for cache key
        provider_name = request_data.model.split("/")[0] if "/" in request_data.model else "openai"

        try:
            # Use cache engine's resolve_or_generate
            async def generate_fn():
                response = await _generate_completion(request_data)
                # Extract just the text content for caching
                content = response["choices"][0]["message"]["content"]
                return {
                    "response": content,
                    "full_response": response,
                }

            result = await cache_engine.resolve_or_generate(
                query=query,
                context=context,
                tenant_id="default",  # Gateway uses single tenant by default
                model=request_data.model,
                provider=provider_name,
                generate_fn=generate_fn,
            )

            # If we got a cached response, wrap it in OpenAI format
            if "full_response" in result:
                return result["full_response"]
            else:
                # Cached hit - reconstruct OpenAI response
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request_data.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": result.get("response", ""),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "x_ico_cache": {
                        "source": result.get("source", "UNKNOWN"),
                        "hit": result.get("source") != "MISS",
                    },
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("chat_completion_failed", request_id=request_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Completion failed: {str(e)}",
            )

    async def _handle_streaming(
        request_data: ChatCompletionRequest, request_id: str
    ) -> StreamingResponse:
        """Handle streaming chat completions."""
        provider = provider_registry.get(request_data.model)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No provider configured for model: {request_data.model}",
            )

        model_name = provider_registry.get_model_name(request_data.model)
        messages_dict = [msg.model_dump(exclude_none=True) for msg in request_data.messages]

        kwargs = {}
        if request_data.temperature is not None:
            kwargs["temperature"] = request_data.temperature
        if request_data.max_tokens is not None:
            kwargs["max_tokens"] = request_data.max_tokens
        if request_data.top_p is not None:
            kwargs["top_p"] = request_data.top_p
        if request_data.stop is not None:
            kwargs["stop"] = request_data.stop

        async def stream_generator():
            try:
                async for chunk in provider.chat_completion_stream(
                    messages_dict, model_name, **kwargs
                ):
                    yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error("stream_failed", request_id=request_id, error=str(e))
                error_chunk = {
                    "error": {
                        "message": str(e),
                        "type": "internal_error",
                    }
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-ID": request_id,
            },
        )

    @app.on_event("shutdown")
    async def shutdown_event():
        """Clean up resources on shutdown."""
        await provider_registry.close_all()
        logger.info("gateway_shutdown_complete")

    return app
