# ICO-Cache OpenAI-Compatible Gateway Implementation

## Overview

The ICO-Cache OpenAI Gateway is a standalone service that provides an OpenAI-compatible API endpoint (`/v1/chat/completions`) with integrated ICO-Cache semantic caching. It acts as a transparent proxy between clients and upstream LLM providers (OpenAI, Anthropic, Google), caching responses to reduce latency, cost, and API calls.

## Architecture

```
Client Application
       ↓
OpenAI-compatible API (/v1/chat/completions)
       ↓
ICO-Cache Gateway
       ↓
  ┌────────────┬──────────────┐
  ↓            ↓              ↓
Cache Layer   Upstream LLM   Health/Observability
(L1/L2/L3)    Providers      (/health, /metrics)
  ↓
Redis + Qdrant
```

### Components

1. **FastAPI Application** (`app.py`): Main HTTP server with request routing, middleware, and error handling
2. **Provider Registry** (`providers.py`): Pluggable LLM provider abstraction supporting OpenAI, Anthropic, and custom providers
3. **Configuration** (`config.py`): Environment-based configuration with sensible defaults
4. **Cache Integration**: Uses existing `CacheEngine` for L1/L2/L3 semantic caching

## Features

### Implemented

- ✅ **POST /v1/chat/completions**: OpenAI-compatible chat completion endpoint
- ✅ **GET /health**: Health check with backend status (Redis, Qdrant, providers)
- ✅ **Streaming Support**: Server-sent events (SSE) for streaming completions
- ✅ **Multi-Provider Support**: OpenAI, Anthropic Claude, Google Gemini
- ✅ **Request ID Propagation**: X-Request-ID header for distributed tracing
- ✅ **Structured Logging**: JSON-formatted logs with request context
- ✅ **OpenTelemetry Integration**: Tracing support via existing ICO-Cache telemetry
- ✅ **Error Handling**: Proper HTTP status codes and error messages
- ✅ **Cache Metadata**: `x_ico_cache` field in responses indicating cache hit/miss

### Provider Support

| Provider   | Format               | Streaming | Status |
|------------|----------------------|-----------|--------|
| OpenAI     | Native OpenAI API    | ✅        | Ready  |
| Anthropic  | Converted to OpenAI  | ✅        | Ready  |
| Google     | OpenAI-compatible    | ✅        | Ready  |
| Custom     | OpenAI-compatible    | ✅        | Ready  |

## Usage

### Installation

The gateway is part of the `ico-cache` Python package:

```bash
pip install ico-cache
```

### Configuration

Configure via environment variables:

```bash
# Server settings
export GATEWAY_HOST=0.0.0.0
export GATEWAY_PORT=8080

# Redis backend
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_PASSWORD=your-password  # optional

# Qdrant backend
export QDRANT_HOST=localhost
export QDRANT_PORT=6333

# Cache settings
export SEMANTIC_THRESHOLD=0.85
export ADAPTIVE_THRESHOLD=true
export TARGET_HIT_RATE=0.80

# Provider API keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=...

# Observability
export LOG_LEVEL=INFO
export LOG_JSON=false
export OTEL_SERVICE_NAME=ico-cache-gateway
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

### Running the Gateway

#### Command Line

```bash
# Using Python module
python -m ico_cache.gateway

# With custom host/port
python -m ico_cache.gateway --host 0.0.0.0 --port 8080

# Development mode with auto-reload
python -m ico_cache.gateway --reload

# Production with multiple workers
python -m ico_cache.gateway --workers 4
```

#### Programmatic

```python
from ico_cache.gateway import create_app, GatewayConfig

config = GatewayConfig.from_env()
app = create_app(config)

# Run with uvicorn
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

#### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install -e packages/ico-cache-py

EXPOSE 8080
CMD ["python", "-m", "ico_cache.gateway", "--host", "0.0.0.0", "--port", "8080"]
```

### Client Usage

The gateway is fully compatible with OpenAI SDKs:

#### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # Gateway handles auth to upstream
)

response = client.chat.completions.create(
    model="openai/gpt-4",
    messages=[
        {"role": "user", "content": "What is the capital of France?"}
    ]
)

print(response.choices[0].message.content)
print(response.x_ico_cache)  # Cache metadata
```

#### JavaScript/TypeScript

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8080/v1',
  apiKey: 'not-needed'
});

const response = await client.chat.completions.create({
  model: 'openai/gpt-4',
  messages: [
    { role: 'user', content: 'What is the capital of France?' }
  ]
});

console.log(response.choices[0].message.content);
console.log(response.x_ico_cache); // Cache metadata
```

#### cURL

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: my-request-123" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [
      {"role": "user", "content": "What is the capital of France?"}
    ],
    "temperature": 0.7
  }'
```

#### Streaming

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080/v1")

stream = client.chat.completions.create(
    model="openai/gpt-4",
    messages=[{"role": "user", "content": "Count to 5"}],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## API Reference

### POST /v1/chat/completions

OpenAI-compatible chat completion endpoint with caching.

**Request Body:**

```json
{
  "model": "openai/gpt-4",           // Format: provider/model-name
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "temperature": 0.7,                // Optional, 0.0-2.0
  "top_p": 1.0,                      // Optional, 0.0-1.0
  "max_tokens": 100,                 // Optional
  "stream": false,                   // Optional, enable streaming
  "stop": ["END"],                   // Optional, stop sequences
  "presence_penalty": 0.0,           // Optional, -2.0 to 2.0
  "frequency_penalty": 0.0           // Optional, -2.0 to 2.0
}
```

**Response (non-streaming):**

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1697123456,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  },
  "x_ico_cache": {
    "source": "L1",     // L1, L2, L3, or MISS
    "hit": true         // true if cached, false if generated
  }
}
```

**Response (streaming):**

Server-sent events (SSE) format:

```
data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":null}]}

data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### GET /health

Health check endpoint returning backend status.

**Response:**

```json
{
  "status": "healthy",  // "healthy" or "degraded"
  "backends": {
    "redis": "connected",     // "connected" or "disconnected"
    "qdrant": "connected"
  },
  "providers": ["openai", "anthropic", "google"]
}
```

## Caching Behavior

### Cache Key Construction

The gateway constructs cache keys from:

1. **Query**: The last user message in the conversation
2. **Context**: All preceding messages (system, user, assistant)
3. **Model**: The full model string (e.g., `openai/gpt-4`)
4. **Provider**: The provider name (e.g., `openai`)

### Cache Layers

- **L1 (Exact Match)**: Exact string match on query + context + model
- **L2 (Semantic)**: Vector similarity on query embeddings (threshold: 0.85)
- **L3 (Context-aware)**: Semantic match considering both query and context

### Cache Bypass

Streaming requests currently bypass the cache and always hit the upstream provider. Future versions may support streaming from cache.

### Cache Metadata

All responses include `x_ico_cache` metadata:

```json
{
  "x_ico_cache": {
    "source": "L1",    // L1, L2, L3, or MISS
    "hit": true        // true if from cache
  }
}
```

## Model Format

Models are specified as `provider/model-name`:

- `openai/gpt-4` → OpenAI GPT-4
- `openai/gpt-3.5-turbo` → OpenAI GPT-3.5 Turbo
- `anthropic/claude-3-opus-20240229` → Anthropic Claude 3 Opus
- `anthropic/claude-3-sonnet-20240229` → Anthropic Claude 3 Sonnet
- `google/gemini-pro` → Google Gemini Pro

For bare model names (e.g., `gpt-4`), the gateway defaults to the `openai` provider.

## Error Handling

The gateway returns standard HTTP status codes:

- **200 OK**: Success
- **400 Bad Request**: Invalid request format or unknown provider
- **422 Unprocessable Entity**: Validation error (missing required fields)
- **429 Too Many Requests**: Upstream rate limit
- **500 Internal Server Error**: Server or upstream provider error
- **503 Service Unavailable**: Backend (Redis/Qdrant) unavailable

Error responses follow OpenAI format:

```json
{
  "error": {
    "message": "No provider configured for model: unknown/model",
    "type": "invalid_request_error",
    "code": "invalid_model"
  }
}
```

## Observability

### Logging

Structured logs include:

- `request_id`: Unique ID for each request (from `X-Request-ID` header or auto-generated)
- `model`: Model requested
- `stream`: Whether streaming was requested
- `duration_ms`: Request duration
- `status_code`: HTTP status

Example log entry:

```json
{
  "event": "request_end",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "method": "POST",
  "path": "/v1/chat/completions",
  "status_code": 200,
  "duration_ms": 234.56,
  "timestamp": "2026-10-07T19:13:41.779Z"
}
```

### Tracing

OpenTelemetry spans are automatically created for:

- HTTP requests
- Cache lookups (via `CacheEngine`)
- Upstream provider calls

Configure via `OTEL_EXPORTER_OTLP_ENDPOINT`.

### Metrics

The gateway inherits ICO-Cache metrics:

- `ico_cache_requests_total`: Total requests by endpoint
- `ico_cache_cache_hits_total`: Cache hits by layer (L1/L2/L3)
- `ico_cache_cache_misses_total`: Cache misses
- `ico_cache_generation_latency_seconds`: Upstream generation latency
- `ico_cache_lookup_latency_seconds`: Cache lookup latency

## Testing

### Running Tests

```bash
# Run gateway tests
pytest packages/ico-cache-py/tests/test_gateway.py -v

# Run with coverage
pytest packages/ico-cache-py/tests/test_gateway.py --cov=ico_cache.gateway --cov-report=html
```

### Test Coverage

The test suite includes:

- Health endpoint tests (healthy, degraded backends)
- Chat completion tests (cache hit, cache miss, parameters)
- Streaming tests
- Multi-provider tests (OpenAI, Anthropic)
- Error handling tests (upstream errors, validation errors)
- Concurrency tests
- Request ID propagation tests

All tests use mocked LLM responses to avoid external API calls.

## Deployment

### Docker Compose

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  qdrant:
    image: qdrant/qdrant:v1.7.0
    ports:
      - "6333:6333"

  gateway:
    build: .
    ports:
      - "8080:8080"
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - LOG_LEVEL=INFO
    depends_on:
      - redis
      - qdrant
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ico-cache-gateway
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ico-cache-gateway
  template:
    metadata:
      labels:
        app: ico-cache-gateway
    spec:
      containers:
      - name: gateway
        image: ico-cache-gateway:latest
        ports:
        - containerPort: 8080
        env:
        - name: REDIS_HOST
          value: redis-service
        - name: QDRANT_HOST
          value: qdrant-service
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: llm-secrets
              key: openai-api-key
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: ico-cache-gateway
spec:
  selector:
    app: ico-cache-gateway
  ports:
  - port: 80
    targetPort: 8080
  type: LoadBalancer
```

## Security Considerations

### Implemented

- ✅ Upstream API keys stored in environment (never logged or returned to clients)
- ✅ Request validation with Pydantic models
- ✅ Proper error handling (no stack traces leaked to clients)
- ✅ Health endpoint does not expose sensitive configuration
- ✅ Redis password support

### Recommended

- Add authentication/authorization for gateway endpoints
- Use HTTPS/TLS in production
- Implement rate limiting per client
- Use secrets management (Vault, AWS Secrets Manager)
- Enable audit logging for compliance

## Limitations

1. **Streaming + Cache**: Streaming requests bypass cache (cache-on-write not yet implemented)
2. **Single Tenant**: Gateway uses a single default tenant ID (multi-tenancy requires additional auth)
3. **No Function Calling**: Function/tool calling not yet supported
4. **No Image Support**: Text-only completions (vision models not supported)

## Future Enhancements

- Cache-on-write for streaming responses
- Multi-tenancy with API key-based tenant routing
- Function calling support
- Vision model support (GPT-4V, Claude 3 with images)
- Adaptive caching policies per model
- Cache warming and preloading
- WebSocket support for bidirectional streaming

## Integration with Existing ICO-Cache

The gateway is designed to integrate seamlessly with the existing ICO-Cache codebase:

- **No modifications** to `accounting.py`, `decision_engine.py`, `cache_engine.py`
- **Uses public APIs**: `CacheEngine.resolve_or_generate()`
- **Shares backends**: Redis, Qdrant, embedder instances
- **Shares telemetry**: Logging, tracing, metrics from `ico_cache.telemetry`
- **Independent**: Can be deployed standalone or alongside the financial RAG demo

## Troubleshooting

### Gateway won't start

Check backend connectivity:

```bash
# Test Redis
redis-cli -h localhost -p 6379 ping

# Test Qdrant
curl http://localhost:6333/collections
```

### Provider errors

Verify API keys are set:

```bash
echo $OPENAI_API_KEY
echo $ANTHROPIC_API_KEY
```

### Cache not working

Check cache engine configuration:

```bash
curl http://localhost:8080/health
```

Verify semantic threshold is reasonable (0.80-0.90 recommended).

### High latency

- Enable `ADAPTIVE_THRESHOLD=true` to auto-tune cache hit rate
- Check upstream provider latency (logged in structured logs)
- Increase worker count for production: `--workers 4`

## References

- OpenAI API Documentation: https://platform.openai.com/docs/api-reference
- Anthropic API Documentation: https://docs.anthropic.com/claude/reference
- ICO-Cache Architecture: See `docs/` directory
- FastAPI Documentation: https://fastapi.tiangolo.com/

---

**Version**: 1.0.0  
**Last Updated**: 2026-10-07  
**Author**: ICO-Cache Team
