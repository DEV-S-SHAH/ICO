"""LLM provider abstraction and registry."""

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
import structlog

from .config import ProviderConfig

logger = structlog.get_logger("ico_cache.gateway.providers")


class LLMProvider(ABC):
    """Base class for LLM providers."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout,
            headers=self._get_headers(),
        )

    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """Get provider-specific headers."""
        pass

    @abstractmethod
    async def chat_completion(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> Dict[str, Any]:
        """Non-streaming chat completion."""
        pass

    @abstractmethod
    def chat_completion_stream(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> AsyncIterator[str]:
        """Streaming chat completion."""
        pass

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider (works for OpenAI, Azure OpenAI, local models)."""

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    async def chat_completion(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> Dict[str, Any]:
        """Non-streaming OpenAI chat completion."""
        payload = {
            "model": model,
            "messages": messages,
            **kwargs,
        }
        payload.pop("stream", None)  # Ensure stream is False

        try:
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "openai_api_error",
                status_code=e.response.status_code,
                detail=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("openai_request_failed", error=str(e))
            raise

    def chat_completion_stream(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> AsyncIterator[str]:
        """Streaming OpenAI chat completion."""
        return self._stream_completion(messages, model, **kwargs)

    async def _stream_completion(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> AsyncIterator[str]:
        """Internal streaming implementation."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }

        try:
            async with self.client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip() == "[DONE]":
                            break
                        yield chunk
        except httpx.HTTPStatusError as e:
            logger.error(
                "openai_stream_error",
                status_code=e.response.status_code,
                detail=await e.response.aread(),
            )
            raise
        except Exception as e:
            logger.error("openai_stream_failed", error=str(e))
            raise


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider (converts to OpenAI format)."""

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return headers

    def _to_anthropic_messages(self, messages: List[Dict[str, Any]]) -> tuple:
        """Convert OpenAI messages to Anthropic format."""
        system_message = None
        anthropic_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                system_message = content
            elif role == "user":
                anthropic_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                anthropic_messages.append({"role": "assistant", "content": content})

        return system_message, anthropic_messages

    def _to_openai_response(self, anthropic_response: Dict[str, Any], model: str) -> Dict[str, Any]:
        """Convert Anthropic response to OpenAI format."""
        content = ""
        if anthropic_response.get("content"):
            content = anthropic_response["content"][0]["text"]

        return {
            "id": anthropic_response.get("id", "chatcmpl-unknown"),
            "object": "chat.completion",
            "created": int(anthropic_response.get("created_at", 0)),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": anthropic_response.get("stop_reason", "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": anthropic_response.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": anthropic_response.get("usage", {}).get("output_tokens", 0),
                "total_tokens": (
                    anthropic_response.get("usage", {}).get("input_tokens", 0)
                    + anthropic_response.get("usage", {}).get("output_tokens", 0)
                ),
            },
        }

    async def chat_completion(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> Dict[str, Any]:
        """Non-streaming Anthropic chat completion."""
        system_message, anthropic_messages = self._to_anthropic_messages(messages)

        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if system_message:
            payload["system"] = system_message
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        try:
            response = await self.client.post("/v1/messages", json=payload)
            response.raise_for_status()
            anthropic_response = response.json()
            return self._to_openai_response(anthropic_response, model)
        except httpx.HTTPStatusError as e:
            logger.error(
                "anthropic_api_error",
                status_code=e.response.status_code,
                detail=e.response.text,
            )
            raise
        except Exception as e:
            logger.error("anthropic_request_failed", error=str(e))
            raise

    def chat_completion_stream(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> AsyncIterator[str]:
        """Streaming Anthropic chat completion."""
        return self._stream_anthropic(messages, model, **kwargs)

    async def _stream_anthropic(
        self, messages: List[Dict[str, Any]], model: str, **kwargs
    ) -> AsyncIterator[str]:
        """Internal streaming implementation for Anthropic."""
        system_message, anthropic_messages = self._to_anthropic_messages(messages)

        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }
        if system_message:
            payload["system"] = system_message
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        try:
            async with self.client.stream("POST", "/v1/messages", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:].strip()
                        if not chunk:
                            continue
                        try:
                            event = json.loads(chunk)
                            # Convert Anthropic stream events to OpenAI format
                            if event.get("type") == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    openai_chunk = {
                                        "id": event.get("message", {}).get("id", "chatcmpl-unknown"),
                                        "object": "chat.completion.chunk",
                                        "created": 0,
                                        "model": model,
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {"content": delta.get("text", "")},
                                                "finish_reason": None,
                                            }
                                        ],
                                    }
                                    yield json.dumps(openai_chunk)
                            elif event.get("type") == "message_stop":
                                openai_chunk = {
                                    "id": "chatcmpl-unknown",
                                    "object": "chat.completion.chunk",
                                    "created": 0,
                                    "model": model,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {},
                                            "finish_reason": "stop",
                                        }
                                    ],
                                }
                                yield json.dumps(openai_chunk)
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPStatusError as e:
            logger.error(
                "anthropic_stream_error",
                status_code=e.response.status_code,
                detail=await e.response.aread(),
            )
            raise
        except Exception as e:
            logger.error("anthropic_stream_failed", error=str(e))
            raise


class ProviderRegistry:
    """Registry for LLM providers."""

    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}

    def register(self, name: str, provider: LLMProvider):
        """Register a provider."""
        self._providers[name] = provider
        logger.info("provider_registered", name=name)

    def get(self, model: str) -> Optional[LLMProvider]:
        """Get provider for a model string (e.g., 'openai/gpt-4', 'anthropic/claude-3')."""
        if "/" in model:
            provider_name = model.split("/")[0]
        else:
            # Default to openai for bare model names
            provider_name = "openai"

        return self._providers.get(provider_name)

    def get_model_name(self, model: str) -> str:
        """Extract the actual model name from a provider/model string."""
        if "/" in model:
            return model.split("/", 1)[1]
        return model

    async def close_all(self):
        """Close all provider clients."""
        for provider in self._providers.values():
            await provider.close()
