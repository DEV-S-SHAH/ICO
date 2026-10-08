"""Integration tests for the OpenAI-compatible gateway."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ico_cache.gateway.app import create_app
from ico_cache.gateway.config import GatewayConfig, ProviderConfig


@pytest.fixture
def mock_redis():
    """Mock Redis store."""
    with patch("ico_cache.gateway.app.RedisStore") as mock:
        store = MagicMock()
        store.client.ping.return_value = True
        mock.return_value = store
        yield store


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant store."""
    with patch("ico_cache.gateway.app.QdrantStore") as mock:
        store = MagicMock()
        store.qc.get_collections.return_value = []
        mock.return_value = store
        yield store


@pytest.fixture
def mock_embedder():
    """Mock embedder."""
    with patch("ico_cache.gateway.app.FastEmbedder") as mock:
        embedder = MagicMock()
        mock.return_value = embedder
        yield embedder


@pytest.fixture
def mock_cache_engine():
    """Mock cache engine."""
    with patch("ico_cache.gateway.app.CacheEngine") as mock:
        engine = MagicMock()

        # Default behavior: cache miss, call generate_fn
        async def mock_resolve_or_generate(query, context, tenant_id, model, provider, generate_fn):
            result = await generate_fn()
            return result

        engine.resolve_or_generate = AsyncMock(side_effect=mock_resolve_or_generate)
        mock.return_value = engine
        yield engine


@pytest.fixture
def test_config():
    """Test gateway configuration."""
    return GatewayConfig(
        host="127.0.0.1",
        port=8080,
        redis_host="localhost",
        redis_port=6379,
        qdrant_host="localhost",
        qdrant_port=6333,
        providers={
            "openai": ProviderConfig(
                name="openai",
                api_key="test-key-123",
                base_url="https://api.openai.com/v1",
            ),
            "anthropic": ProviderConfig(
                name="anthropic",
                api_key="test-anthropic-key",
                base_url="https://api.anthropic.com",
            ),
        },
    )


@pytest.fixture
def client(test_config, mock_redis, mock_qdrant, mock_embedder, mock_cache_engine):
    """Test client with mocked dependencies."""
    app = create_app(test_config)
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check_all_healthy(self, client, mock_redis, mock_qdrant):
        """Test health check when all backends are healthy."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["backends"]["redis"] == "connected"
        assert data["backends"]["qdrant"] == "connected"
        assert "openai" in data["providers"]
        assert "anthropic" in data["providers"]

    def test_health_check_redis_down(self, client, mock_redis):
        """Test health check when Redis is down."""
        mock_redis.client.ping.side_effect = Exception("Connection failed")

        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "degraded"
        assert data["backends"]["redis"] == "disconnected"

    def test_health_check_qdrant_down(self, client, mock_qdrant):
        """Test health check when Qdrant is down."""
        mock_qdrant.qc.get_collections.side_effect = Exception("Connection failed")

        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "degraded"
        assert data["backends"]["qdrant"] == "disconnected"


class TestChatCompletions:
    """Tests for the /v1/chat/completions endpoint."""

    @pytest.fixture
    def mock_openai_response(self):
        """Mock OpenAI API response."""
        return {
            "id": "chatcmpl-test123",
            "object": "chat.completion",
            "created": 1697123456,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "This is a test response from GPT-4.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }

    @pytest.fixture
    def sample_request(self):
        """Sample chat completion request."""
        return {
            "model": "openai/gpt-4",
            "messages": [
                {"role": "user", "content": "What is the capital of France?"}
            ],
            "temperature": 0.7,
        }

    def test_chat_completion_cache_miss(
        self, client, sample_request, mock_openai_response, mock_cache_engine
    ):
        """Test chat completion with cache miss."""
        async def mock_post(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value=mock_openai_response)
            mock_response.raise_for_status = MagicMock()
            return mock_response

        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post", side_effect=mock_post):
            response = client.post("/v1/chat/completions", json=sample_request)

            assert response.status_code == 200
            data = response.json()

            assert data["choices"][0]["message"]["content"] == "This is a test response from GPT-4."
            assert "X-Request-ID" in response.headers

    def test_chat_completion_cache_hit(
        self, client, sample_request, mock_openai_response, mock_cache_engine
    ):
        """Test chat completion with cache hit."""
        # Mock cache engine to return cached response
        async def mock_cached_response(query, context, tenant_id, model, provider, generate_fn):
            return {
                "response": "Cached response: Paris is the capital.",
                "source": "L1",
            }

        mock_cache_engine.resolve_or_generate = AsyncMock(side_effect=mock_cached_response)

        response = client.post("/v1/chat/completions", json=sample_request)

        assert response.status_code == 200
        data = response.json()

        assert data["choices"][0]["message"]["content"] == "Cached response: Paris is the capital."
        assert data.get("x_ico_cache", {}).get("source") == "L1"
        assert data.get("x_ico_cache", {}).get("hit") is True

    def test_chat_completion_missing_model(self, client):
        """Test chat completion with missing model."""
        request = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ],
        }

        response = client.post("/v1/chat/completions", json=request)
        assert response.status_code == 422  # Validation error

    def test_chat_completion_unknown_provider(self, client):
        """Test chat completion with unknown provider."""
        request = {
            "model": "unknown-provider/model",
            "messages": [
                {"role": "user", "content": "Hello"}
            ],
        }

        response = client.post("/v1/chat/completions", json=request)
        assert response.status_code == 400
        assert "No provider configured" in response.json()["detail"]

    def test_chat_completion_invalid_messages(self, client):
        """Test chat completion with invalid message format."""
        request = {
            "model": "openai/gpt-4",
            "messages": "not a list",
        }

        response = client.post("/v1/chat/completions", json=request)
        assert response.status_code == 422

    def test_chat_completion_with_context(
        self, client, mock_openai_response, mock_cache_engine
    ):
        """Test chat completion with conversation context."""
        request = {
            "model": "openai/gpt-4",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"},
                {"role": "user", "content": "What about 3+3?"},
            ],
            "temperature": 0.5,
        }

        async def mock_post(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value=mock_openai_response)
            mock_response.raise_for_status = MagicMock()
            return mock_response

        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post", side_effect=mock_post):
            response = client.post("/v1/chat/completions", json=request)

            assert response.status_code == 200
            # Verify cache engine was called with proper context
            assert mock_cache_engine.resolve_or_generate.called

    def test_chat_completion_with_parameters(
        self, client, mock_openai_response
    ):
        """Test chat completion with various parameters."""
        request = {
            "model": "openai/gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.9,
            "top_p": 0.95,
            "max_tokens": 100,
            "presence_penalty": 0.5,
            "frequency_penalty": 0.5,
            "stop": ["END"],
        }

        async def mock_post(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value=mock_openai_response)
            mock_response.raise_for_status = MagicMock()
            return mock_response

        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post", side_effect=mock_post):
            response = client.post("/v1/chat/completions", json=request)

            assert response.status_code == 200


class TestStreamingCompletions:
    """Tests for streaming chat completions."""

    @pytest.fixture
    def sample_streaming_request(self):
        """Sample streaming request."""
        return {
            "model": "openai/gpt-4",
            "messages": [{"role": "user", "content": "Count to 3"}],
            "stream": True,
        }

    def test_streaming_completion(self, client, sample_streaming_request):
        """Test streaming chat completion."""
        mock_chunks = [
            '{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"One"},"finish_reason":null}]}',
            '{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{"content":", two"},"finish_reason":null}]}',
            '{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{"content":", three"},"finish_reason":null}]}',
            '{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1697123456,"model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
        ]

        async def mock_stream(*args, **kwargs):
            for chunk in mock_chunks:
                yield chunk

        with patch("ico_cache.gateway.providers.OpenAIProvider.chat_completion_stream") as mock_stream_method:
            mock_stream_method.return_value = mock_stream()

            response = client.post("/v1/chat/completions", json=sample_streaming_request)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            # Read streaming response
            content = response.text
            assert "data: " in content
            assert "[DONE]" in content

    def test_streaming_with_cache_disabled(self, client, sample_streaming_request):
        """Test that streaming bypasses cache."""
        # Streaming should not use cache (for now)
        response = client.post("/v1/chat/completions", json=sample_streaming_request)

        # Should still work but won't hit cache
        assert response.status_code == 200


class TestAnthropicProvider:
    """Tests for Anthropic provider integration."""

    @pytest.fixture
    def anthropic_request(self):
        """Sample request for Anthropic."""
        return {
            "model": "anthropic/claude-3-opus-20240229",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is AI?"},
            ],
        }

    @pytest.fixture
    def mock_anthropic_response(self):
        """Mock Anthropic API response."""
        return {
            "id": "msg_test123",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "AI stands for Artificial Intelligence.",
                }
            ],
            "model": "claude-3-opus-20240229",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 15,
                "output_tokens": 25,
            },
        }

    def test_anthropic_completion(
        self, client, anthropic_request, mock_anthropic_response
    ):
        """Test chat completion with Anthropic provider."""
        async def mock_post(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value=mock_anthropic_response)
            mock_response.raise_for_status = MagicMock()
            return mock_response

        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post", side_effect=mock_post):
            response = client.post("/v1/chat/completions", json=anthropic_request)

            assert response.status_code == 200
            data = response.json()

            # Verify OpenAI-compatible format
            assert "choices" in data
            assert data["choices"][0]["message"]["content"] == "AI stands for Artificial Intelligence."
            assert "usage" in data


class TestErrorHandling:
    """Tests for error handling."""

    def test_upstream_api_error(self, client):
        """Test handling of upstream API errors."""
        request = {
            "model": "openai/gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post") as mock_post:
            from httpx import Response, Request

            mock_response = Response(
                status_code=429,
                content=b'{"error": {"message": "Rate limit exceeded"}}',
                request=Request("POST", "https://api.openai.com/v1/chat/completions"),
            )
            mock_post.return_value = mock_response

            response = client.post("/v1/chat/completions", json=request)

            assert response.status_code == 500

    def test_request_id_propagation(self, client, mock_openai_response=None):
        """Test that request IDs are propagated."""
        request = {
            "model": "openai/gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        custom_request_id = "test-request-123"

        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post") as mock_post:
            mock_response = AsyncMock()
            mock_response.json.return_value = {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1697123456,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            response = client.post(
                "/v1/chat/completions",
                json=request,
                headers={"X-Request-ID": custom_request_id},
            )

            assert response.headers.get("X-Request-ID") == custom_request_id


class TestConcurrency:
    """Tests for concurrent requests."""

    def test_concurrent_requests(self, client, mock_openai_response=None):
        """Test handling of concurrent requests."""
        from concurrent.futures import ThreadPoolExecutor

        request = {
            "model": "openai/gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        async def mock_post(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.json = MagicMock(return_value={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1697123456,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            })
            mock_response.raise_for_status = MagicMock()
            return mock_response

        def make_request():
            return client.post("/v1/chat/completions", json=request)

        # Make 5 concurrent requests
        with patch("ico_cache.gateway.providers.httpx.AsyncClient.post", side_effect=mock_post):
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(make_request) for _ in range(5)]
                responses = [f.result() for f in futures]

        # All should succeed
        assert all(r.status_code == 200 for r in responses)
