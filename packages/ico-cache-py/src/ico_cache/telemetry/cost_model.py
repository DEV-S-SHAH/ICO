"""Cost model for token accounting.

Provides per-provider, per-model pricing for accurate cost estimation.
Prices are in USD per 1M tokens (input/output).
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for a specific model."""
    input_usd_per_million: float
    output_usd_per_million: float
    provider: str
    model: str


# Default pricing (as of 2024-10). Should be updated periodically.
# Prices in USD per 1M tokens.
DEFAULT_PRICING: Dict[str, ModelPricing] = {
    # OpenAI
    "openai:gpt-4o": ModelPricing(2.50, 10.00, "openai", "gpt-4o"),
    "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini"),
    "openai:gpt-4-turbo": ModelPricing(10.00, 30.00, "openai", "gpt-4-turbo"),
    "openai:gpt-4": ModelPricing(30.00, 60.00, "openai", "gpt-4"),
    "openai:gpt-3.5-turbo": ModelPricing(0.50, 1.50, "openai", "gpt-3.5-turbo"),
    "openai:text-embedding-3-small": ModelPricing(0.02, 0.02, "openai", "text-embedding-3-small"),
    "openai:text-embedding-3-large": ModelPricing(0.13, 0.13, "openai", "text-embedding-3-large"),

    # Anthropic
    "anthropic:claude-3-5-sonnet-20241022": ModelPricing(3.00, 15.00, "anthropic", "claude-3-5-sonnet-20241022"),
    "anthropic:claude-3-5-haiku-20241022": ModelPricing(0.80, 4.00, "anthropic", "claude-3-5-haiku-20241022"),
    "anthropic:claude-3-opus-20240229": ModelPricing(15.00, 75.00, "anthropic", "claude-3-opus-20240229"),
    "anthropic:claude-3-sonnet-20240229": ModelPricing(3.00, 15.00, "anthropic", "claude-3-sonnet-20240229"),
    "anthropic:claude-3-haiku-20240307": ModelPricing(0.25, 1.25, "anthropic", "claude-3-haiku-20240307"),

    # Google
    "gemini:gemini-1.5-pro": ModelPricing(3.50, 10.50, "gemini", "gemini-1.5-pro"),
    "gemini:gemini-1.5-flash": ModelPricing(0.075, 0.30, "gemini", "gemini-1.5-flash"),
    "gemini:text-embedding-004": ModelPricing(0.01, 0.01, "gemini", "text-embedding-004"),

    # Local/Ollama (zero cost)
    "ollama:llama-3.1-70b": ModelPricing(0.0, 0.0, "ollama", "llama-3.1-70b"),
    "ollama:llama-3.1-8b": ModelPricing(0.0, 0.0, "ollama", "llama-3.1-8b"),
    "ollama:mistral-7b": ModelPricing(0.0, 0.0, "ollama", "mistral-7b"),
    "ollama:codellama-7b": ModelPricing(0.0, 0.0, "ollama", "codellama-7b"),

    # Together AI
    "together:meta-llama-3.1-70b": ModelPricing(0.88, 0.88, "together", "meta-llama-3.1-70b"),
    "together:meta-llama-3.1-8b": ModelPricing(0.18, 0.18, "together", "meta-llama-3.1-8b"),
    "together:mistral-7b": ModelPricing(0.20, 0.20, "together", "mistral-7b"),

    # Fireworks
    "fireworks:llama-3.1-70b": ModelPricing(0.90, 0.90, "fireworks", "llama-3.1-70b"),
    "fireworks:llama-3.1-8b": ModelPricing(0.20, 0.20, "fireworks", "llama-3.1-8b"),

    # Groq
    "groq:llama-3.1-70b": ModelPricing(0.59, 0.79, "groq", "llama-3.1-70b"),
    "groq:llama-3.1-8b": ModelPricing(0.05, 0.08, "groq", "llama-3.1-8b"),
    "groq:mixtral-8x7b": ModelPricing(0.27, 0.27, "groq", "mixtral-8x7b"),

    # Cohere
    "cohere:command-r-plus": ModelPricing(3.00, 15.00, "cohere", "command-r-plus"),
    "cohere:command-r": ModelPricing(0.50, 1.50, "cohere", "command-r"),
    "cohere:embed-english-v3.0": ModelPricing(0.10, 0.10, "cohere", "embed-english-v3.0"),
}


class CostModel:
    """Cost model for estimating LLM API costs."""

    def __init__(self, pricing: Optional[Dict[str, ModelPricing]] = None):
        """Initialize with custom pricing or defaults."""
        self._pricing = {**DEFAULT_PRICING, **(pricing or {})}

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        """Get pricing for a provider/model combination."""
        key = f"{provider}:{model}"
        return self._pricing.get(key)

    def estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Optional[float]:
        """Estimate cost in USD for a request.

        Returns None if pricing not available for the model.
        """
        pricing = self.get_pricing(provider, model)
        if not pricing:
            return None

        input_cost = (input_tokens / 1_000_000) * pricing.input_usd_per_million
        output_cost = (output_tokens / 1_000_000) * pricing.output_usd_per_million
        return input_cost + output_cost

    def estimate_cost_from_usage(
        self,
        provider: str,
        model: str,
        usage: dict,
    ) -> Optional[float]:
        """Estimate cost from LiteLLM-style usage dict.

        Expected keys: prompt_tokens, completion_tokens, total_tokens
        """
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        return self.estimate_cost(provider, model, input_tokens, output_tokens)

    def register_model(self, pricing: ModelPricing) -> None:
        """Register or update pricing for a model."""
        key = f"{pricing.provider}:{pricing.model}"
        self._pricing[key] = pricing

    def get_all_models(self) -> Dict[str, ModelPricing]:
        """Get all registered model pricing."""
        return dict(self._pricing)


# Global default cost model instance
_default_cost_model: Optional[CostModel] = None


def get_cost_model() -> CostModel:
    """Get the global default cost model."""
    global _default_cost_model
    if _default_cost_model is None:
        _default_cost_model = CostModel()
    return _default_cost_model


def set_cost_model(model: CostModel) -> None:
    """Set the global default cost model."""
    global _default_cost_model
    _default_cost_model = model


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """Convenience function to estimate cost using default model."""
    return get_cost_model().estimate_cost(provider, model, input_tokens, output_tokens)
