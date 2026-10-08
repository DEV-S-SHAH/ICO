"""Provider-neutral token accounting adapters.

Extracts token usage from various LLM provider response formats and normalizes
to a common UsageInfo structure. Provides model fingerprinting for cache key consistency.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import hashlib


class UsageSource(str, Enum):
    """Source of token usage information."""
    PROVIDER_RESPONSE = "provider_response"      # From provider's usage field
    ESTIMATED = "estimated"                      # Estimated via tokenizer
    LITELLM = "litellm"                          # Via LiteLLM wrapper
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UsageInfo:
    """Normalized token usage information."""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    usage_source: UsageSource = UsageSource.UNKNOWN
    raw_usage: Dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""

    def __post_init__(self):
        # Validate consistency
        if self.total_tokens != self.input_tokens + self.output_tokens:
            object.__setattr__(self, 'total_tokens', self.input_tokens + self.output_tokens)

    @property
    def has_cached_tokens(self) -> bool:
        return self.cached_input_tokens > 0

    @property
    def has_reasoning_tokens(self) -> bool:
        return self.reasoning_tokens > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "usage_source": self.usage_source.value,
            "provider": self.provider,
            "model": self.model,
        }


class ProviderTokenAdapter(ABC):
    """Abstract base class for provider-specific token extraction."""

    @abstractmethod
    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        """Extract token usage from provider response.

        Args:
            response: Raw response dict from provider API

        Returns:
            Normalized UsageInfo
        """
        pass

    @abstractmethod
    def supports_cached_tokens(self) -> bool:
        """Whether this provider reports cached input tokens."""
        pass

    @abstractmethod
    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        """Generate deterministic model fingerprint for cache keys.

        Includes model name, provider, and generation parameters that affect output.
        """
        pass

    def _deterministic_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Extract only deterministic params that affect output."""
        return {
            k: v for k, v in params.items()
            if k in ("temperature", "top_p", "top_k", "max_tokens", "seed", "stop")
        }

    def _compute_fingerprint(self, provider: str, model: str, params: Dict[str, Any]) -> str:
        """Compute SHA256 fingerprint from components."""
        det_params = self._deterministic_params(params)
        parts = [provider, model, str(sorted(det_params.items()))]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


class OpenAIAdapter(ProviderTokenAdapter):
    """Adapter for OpenAI and OpenAI-compatible APIs."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        usage = response.get("usage", {})
        if not usage:
            return UsageInfo(
                input_tokens=0, output_tokens=0, total_tokens=0,
                usage_source=UsageSource.UNKNOWN,
                provider="openai", model=response.get("model", "")
            )

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        # OpenAI reports cached tokens in prompt_tokens_details
        cached_input = 0
        prompt_details = usage.get("prompt_tokens_details", {})
        if isinstance(prompt_details, dict):
            cached_input = prompt_details.get("cached_tokens", 0)

        # Reasoning tokens (for o1 models)
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=reasoning_tokens,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage=usage,
            provider="openai",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return True

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("openai", model, params)


class AnthropicAdapter(ProviderTokenAdapter):
    """Adapter for Anthropic API."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        usage = response.get("usage", {})
        if not usage:
            return UsageInfo(
                input_tokens=0, output_tokens=0, total_tokens=0,
                usage_source=UsageSource.UNKNOWN,
                provider="anthropic", model=response.get("model", "")
            )

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Anthropic reports cache reads in cache_read_input_tokens
        cached_input = usage.get("cache_read_input_tokens", 0)

        # Cache creation tokens (for prompt caching)
        _cache_creation = usage.get("cache_creation_input_tokens", 0)

        # Total from provider or computed
        total_tokens = input_tokens + output_tokens

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=0,  # Anthropic doesn't separate reasoning
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage=usage,
            provider="anthropic",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return True

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("anthropic", model, params)


class GoogleAdapter(ProviderTokenAdapter):
    """Adapter for Google/Gemini API."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        # Google uses usageMetadata
        usage = response.get("usageMetadata", {})
        if not usage:
            # Check for candidates[0].tokenCount (older format)
            candidates = response.get("candidates", [])
            if candidates and "tokenCount" in candidates[0]:
                total = candidates[0]["tokenCount"]
                return UsageInfo(
                    input_tokens=0, output_tokens=0, total_tokens=total,
                    usage_source=UsageSource.ESTIMATED,
                    provider="gemini", model=response.get("model", ""),
                )
            return UsageInfo(
                input_tokens=0, output_tokens=0, total_tokens=0,
                usage_source=UsageSource.UNKNOWN,
                provider="gemini", model=response.get("model", ""),
            )

        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)
        total_tokens = usage.get("totalTokenCount", input_tokens + output_tokens)

        # Google doesn't report cached tokens separately in standard API
        cached_input = 0
        # Check for cachedContentTokenCount (Vertex AI feature)
        if "cachedContentTokenCount" in usage:
            cached_input = usage.get("cachedContentTokenCount", 0)

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=0,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage=usage,
            provider="gemini",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        # Only with Vertex AI cached content
        return False

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("gemini", model, params)


class TogetherAdapter(ProviderTokenAdapter):
    """Adapter for Together AI API (OpenAI-compatible)."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        usage = response.get("usage", {})
        if not usage:
            return UsageInfo(
                input_tokens=0, output_tokens=0, total_tokens=0,
                usage_source=UsageSource.UNKNOWN,
                provider="together", model=response.get("model", ""),
            )

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        # Together doesn't currently report cached tokens
        cached_input = 0

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=0,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage=usage,
            provider="together",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return False

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("together", model, params)


class FireworksAdapter(ProviderTokenAdapter):
    """Adapter for Fireworks AI API (OpenAI-compatible)."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        usage = response.get("usage", {})
        if not usage:
            return UsageInfo(
                input_tokens=0, output_tokens=0, total_tokens=0,
                usage_source=UsageSource.UNKNOWN,
                provider="fireworks", model=response.get("model", ""),
            )

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        cached_input = 0  # Not currently reported

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=0,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage=usage,
            provider="fireworks",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return False

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("fireworks", model, params)


class GroqAdapter(ProviderTokenAdapter):
    """Adapter for Groq API (OpenAI-compatible)."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        usage = response.get("usage", {})
        if not usage:
            return UsageInfo(
                input_tokens=0, output_tokens=0, total_tokens=0,
                usage_source=UsageSource.UNKNOWN,
                provider="groq", model=response.get("model", ""),
            )

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        # Groq reports x_groq usage extensions
        cached_input = 0
        if "x_groq" in usage:
            cached_input = usage["x_groq"].get("cached_tokens", 0)

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=0,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage=usage,
            provider="groq",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return True  # Via x_groq extension

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("groq", model, params)


class CohereAdapter(ProviderTokenAdapter):
    """Adapter for Cohere API."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        # Cohere uses meta.tokens or token_count
        meta = response.get("meta", {})
        tokens = meta.get("tokens", {}) if isinstance(meta.get("tokens"), dict) else {}

        if tokens:
            input_tokens = tokens.get("input_tokens", 0)
            output_tokens = tokens.get("output_tokens", 0)
        else:
            # Fallback to token_count
            input_tokens = response.get("token_count", {}).get("prompt_tokens", 0)
            output_tokens = response.get("token_count", {}).get("completion_tokens", 0)

        total_tokens = input_tokens + output_tokens

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=0,  # Cohere doesn't report cached
            reasoning_tokens=0,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage={"meta": meta, "token_count": response.get("token_count", {})},
            provider="cohere",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return False

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("cohere", model, params)


class OllamaAdapter(ProviderTokenAdapter):
    """Adapter for Ollama local API."""

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        # Ollama returns eval_count and prompt_eval_count
        input_tokens = response.get("prompt_eval_count", 0)
        output_tokens = response.get("eval_count", 0)
        total_tokens = input_tokens + output_tokens

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=0,
            reasoning_tokens=0,
            usage_source=UsageSource.PROVIDER_RESPONSE,
            raw_usage={"prompt_eval_count": input_tokens, "eval_count": output_tokens},
            provider="ollama",
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return False

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        return self._compute_fingerprint("ollama", model, params)


class LiteLLMAdapter(ProviderTokenAdapter):
    """Adapter for LiteLLM unified response format.

    LiteLLM normalizes responses to OpenAI format, so this delegates to OpenAIAdapter
    but preserves the original provider info.
    """

    def __init__(self):
        self._openai_adapter = OpenAIAdapter()

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        # LiteLLM adds _hidden_params with original provider info
        hidden = response.get("_hidden_params", {})
        original_provider = hidden.get("model", "").split("/")[0] if "/" in hidden.get("model", "") else "openai"
        original_model = hidden.get("model", response.get("model", ""))

        usage_info = self._openai_adapter.extract_usage(response)

        # Override provider/model with original
        return UsageInfo(
            input_tokens=usage_info.input_tokens,
            output_tokens=usage_info.output_tokens,
            total_tokens=usage_info.total_tokens,
            cached_input_tokens=usage_info.cached_input_tokens,
            reasoning_tokens=usage_info.reasoning_tokens,
            usage_source=UsageSource.LITELLM,
            raw_usage=usage_info.raw_usage,
            provider=original_provider,
            model=original_model,
        )

    def supports_cached_tokens(self) -> bool:
        return True  # Depends on underlying provider

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        # Extract provider from model string (e.g., "anthropic/claude-3" -> "anthropic")
        provider = "openai"
        if "/" in model:
            provider = model.split("/")[0]
        return self._compute_fingerprint(provider, model, params)


class EstimationAdapter(ProviderTokenAdapter):
    """Fallback adapter that estimates tokens using a tokenizer.

    Used when provider doesn't return usage info.
    """

    def __init__(self, tokenizer=None):
        self._tokenizer = tokenizer

    def extract_usage(self, response: Dict[str, Any]) -> UsageInfo:
        # Try to estimate from response content
        input_tokens = 0
        output_tokens = 0

        if self._tokenizer:
            # Estimate from messages and response text
            messages = response.get("messages", [])
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    input_tokens += len(self._tokenizer.encode(content))

            # Estimate output from choices
            choices = response.get("choices", [])
            for choice in choices:
                content = choice.get("message", {}).get("content", "")
                if isinstance(content, str):
                    output_tokens += len(self._tokenizer.encode(content))
        else:
            # Rough heuristic: ~4 chars per token
            messages = response.get("messages", [])
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    input_tokens += len(content) // 4

            choices = response.get("choices", [])
            for choice in choices:
                content = choice.get("message", {}).get("content", "")
                if isinstance(content, str):
                    output_tokens += len(content) // 4

        return UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cached_input_tokens=0,
            reasoning_tokens=0,
            usage_source=UsageSource.ESTIMATED,
            raw_usage={},
            provider=response.get("provider", "unknown"),
            model=response.get("model", ""),
        )

    def supports_cached_tokens(self) -> bool:
        return False

    def model_fingerprint(self, model: str, params: Dict[str, Any]) -> str:
        provider = "unknown"
        if "/" in model:
            provider = model.split("/")[0]
        return self._compute_fingerprint(provider, model, params)


class ProviderAdapterRegistry:
    """Registry of provider adapters with fallback to estimation."""

    def __init__(self):
        self._adapters: Dict[str, ProviderTokenAdapter] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in adapters."""
        # Direct provider adapters
        self.register("openai", OpenAIAdapter())
        self.register("anthropic", AnthropicAdapter())
        self.register("gemini", GoogleAdapter())
        self.register("google", GoogleAdapter())  # alias
        self.register("together", TogetherAdapter())
        self.register("fireworks", FireworksAdapter())
        self.register("groq", GroqAdapter())
        self.register("cohere", CohereAdapter())
        self.register("ollama", OllamaAdapter())

        # LiteLLM adapter for unified format
        self.register("litellm", LiteLLMAdapter())

        # Fallback estimation
        self._estimation_adapter = EstimationAdapter()

    def register(self, provider: str, adapter: ProviderTokenAdapter) -> None:
        """Register an adapter for a provider."""
        self._adapters[provider.lower()] = adapter

    def get_adapter(self, provider: str) -> ProviderTokenAdapter:
        """Get adapter for provider, with fallback to estimation."""
        provider_lower = provider.lower()

        # Direct match
        if provider_lower in self._adapters:
            return self._adapters[provider_lower]

        # Try prefix match (e.g., "openai/gpt-4o" -> "openai")
        for prefix in self._adapters:
            if provider_lower.startswith(prefix + "/"):
                return self._adapters[prefix]

        # Fallback to estimation
        return self._estimation_adapter

    def _has_estimable_content(self, response: Dict[str, Any]) -> bool:
        """True when the response carries text we can estimate tokens from."""
        for choice in response.get("choices", []):
            content = choice.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                return True
        for msg in response.get("messages", []):
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return True
        content = response.get("content") if not response.get("choices") and not response.get("messages") else None
        if isinstance(content, str) and content.strip():
            return True
        return False

    def extract_usage(self, provider: str, response: Dict[str, Any]) -> UsageInfo:
        """Extract usage using the appropriate adapter.

        If the primary adapter can't attribute usage (UNKNOWN) but the
        response carries content, fall back to the estimation adapter so
        token accounting still has a grounded estimate rather than nothing.
        """
        adapter = self.get_adapter(provider)
        usage = adapter.extract_usage(response)
        if usage.usage_source == UsageSource.UNKNOWN and self._has_estimable_content(response):
            return self._estimation_adapter.extract_usage(response)
        return usage

    def model_fingerprint(self, provider: str, model: str, params: Dict[str, Any]) -> str:
        """Generate model fingerprint using appropriate adapter."""
        adapter = self.get_adapter(provider)
        return adapter.model_fingerprint(model, params)

    def supports_cached_tokens(self, provider: str) -> bool:
        """Check if provider supports cached token reporting."""
        adapter = self.get_adapter(provider)
        return adapter.supports_cached_tokens()


# Global registry instance
_default_registry: Optional[ProviderAdapterRegistry] = None


def get_provider_registry() -> ProviderAdapterRegistry:
    """Get the global provider adapter registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ProviderAdapterRegistry()
    return _default_registry


def set_provider_registry(registry: ProviderAdapterRegistry) -> None:
    """Set the global provider adapter registry."""
    global _default_registry
    _default_registry = registry


__all__ = [
    "UsageSource",
    "UsageInfo",
    "ProviderTokenAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GoogleAdapter",
    "TogetherAdapter",
    "FireworksAdapter",
    "GroqAdapter",
    "CohereAdapter",
    "OllamaAdapter",
    "LiteLLMAdapter",
    "EstimationAdapter",
    "ProviderAdapterRegistry",
    "get_provider_registry",
    "set_provider_registry",
]
