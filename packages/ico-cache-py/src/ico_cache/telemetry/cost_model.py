"""Cost model for token accounting with pricing versioning.

Provides per-provider, per-model pricing for accurate cost estimation.
Prices are in USD per 1M tokens (input/output).

Security: Pricing registry is frozen after initialization to prevent
runtime manipulation. Integrity checks validate pricing on access.

Phase 3A.5: Added pricing versioning for historical cost accuracy.
"""

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from types import MappingProxyType

logger = logging.getLogger("ico_cache.telemetry.cost_model")


@dataclass(frozen=True)
class PricingVersion:
    """Version metadata for a pricing entry.

    Enables historical cost calculation by tracking when pricing was effective.
    """
    version: str                    # e.g., "2024.10", "v1.2.3"
    effective_from: datetime        # When this pricing became effective
    effective_to: Optional[datetime] = None  # When it was superseded (None = current)
    source: str = "manual"          # Source: "manual", "provider_api", "config_file"
    notes: str = ""                 # Human-readable notes

    def __post_init__(self):
        if self.effective_from.tzinfo is None:
            object.__setattr__(self, 'effective_from',
                self.effective_from.replace(tzinfo=timezone.utc))
        if self.effective_to is not None and self.effective_to.tzinfo is None:
            object.__setattr__(self, 'effective_to',
                self.effective_to.replace(tzinfo=timezone.utc))

    def is_effective_at(self, timestamp: datetime) -> bool:
        """Check if this version was effective at given timestamp."""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if timestamp < self.effective_from:
            return False
        if self.effective_to is not None and timestamp > self.effective_to:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source": self.source,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ModelPricing:
    """Pricing for a specific model. Immutable after creation."""

    input_usd_per_million: float
    output_usd_per_million: float
    provider: str
    model: str
    version: Optional[PricingVersion] = None  # NEW: Version metadata
    cached_usd_per_million: float = 0.0       # NEW: Cached input token pricing
    reasoning_usd_per_million: float = 0.0    # NEW: Reasoning token pricing

    def __post_init__(self):
        # Validation - hard gates
        if not isinstance(self.input_usd_per_million, (int, float)) or self.input_usd_per_million < 0:
            raise ValueError("input_usd_per_million must be non-negative")
        if not isinstance(self.output_usd_per_million, (int, float)) or self.output_usd_per_million < 0:
            raise ValueError("output_usd_per_million must be non-negative")
        if not isinstance(self.cached_usd_per_million, (int, float)) or self.cached_usd_per_million < 0:
            raise ValueError("cached_usd_per_million must be non-negative")
        if not isinstance(self.reasoning_usd_per_million, (int, float)) or self.reasoning_usd_per_million < 0:
            raise ValueError("reasoning_usd_per_million must be non-negative")
        if not self.provider or not isinstance(self.provider, str):
            raise ValueError("provider is required")
        if not self.model or not isinstance(self.model, str):
            raise ValueError("model is required")

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        """Calculate cost for given token counts including cached/reasoning."""
        if not isinstance(input_tokens, int) or input_tokens < 0:
            raise ValueError("input_tokens must be non-negative integer")
        if not isinstance(output_tokens, int) or output_tokens < 0:
            raise ValueError("output_tokens must be non-negative integer")
        if not isinstance(cached_input_tokens, int) or cached_input_tokens < 0:
            raise ValueError("cached_input_tokens must be non-negative integer")
        if not isinstance(reasoning_tokens, int) or reasoning_tokens < 0:
            raise ValueError("reasoning_tokens must be non-negative integer")

        input_cost = (input_tokens / 1_000_000) * self.input_usd_per_million
        output_cost = (output_tokens / 1_000_000) * self.output_usd_per_million
        cached_cost = (cached_input_tokens / 1_000_000) * self.cached_usd_per_million
        reasoning_cost = (reasoning_tokens / 1_000_000) * self.reasoning_usd_per_million
        return input_cost + output_cost + cached_cost + reasoning_cost

    def with_version(self, version: PricingVersion) -> "ModelPricing":
        """Return new ModelPricing with version attached (for historical records)."""
        return ModelPricing(
            input_usd_per_million=self.input_usd_per_million,
            output_usd_per_million=self.output_usd_per_million,
            provider=self.provider,
            model=self.model,
            version=version,
            cached_usd_per_million=self.cached_usd_per_million,
            reasoning_usd_per_million=self.reasoning_usd_per_million,
        )


# Default pricing (as of 2024-10). Should be updated periodically.
# Prices in USD per 1M tokens.
_DEFAULT_PRICING: Dict[str, ModelPricing] = {
    # OpenAI
    "openai:gpt-4o": ModelPricing(2.50, 10.00, "openai", "gpt-4o",
        cached_usd_per_million=1.25),  # 50% discount for cached
    "openai:gpt-4o-mini": ModelPricing(0.15, 0.60, "openai", "gpt-4o-mini",
        cached_usd_per_million=0.075),
    "openai:gpt-4-turbo": ModelPricing(10.00, 30.00, "openai", "gpt-4-turbo",
        cached_usd_per_million=5.00),
    "openai:gpt-4": ModelPricing(30.00, 60.00, "openai", "gpt-4"),
    "openai:gpt-3.5-turbo": ModelPricing(0.50, 1.50, "openai", "gpt-3.5-turbo"),
    "openai:text-embedding-3-small": ModelPricing(0.02, 0.02, "openai", "text-embedding-3-small"),
    "openai:text-embedding-3-large": ModelPricing(0.13, 0.13, "openai", "text-embedding-3-large"),
    "openai:o1-preview": ModelPricing(15.00, 60.00, "openai", "o1-preview",
        reasoning_usd_per_million=60.00),
    "openai:o1-mini": ModelPricing(3.00, 12.00, "openai", "o1-mini",
        reasoning_usd_per_million=12.00),

    # Anthropic
    "anthropic:claude-3-5-sonnet-20241022": ModelPricing(3.00, 15.00, "anthropic", "claude-3-5-sonnet-20241022",
        cached_usd_per_million=0.30),  # 90% discount for cache read
    "anthropic:claude-3-5-haiku-20241022": ModelPricing(0.80, 4.00, "anthropic", "claude-3-5-haiku-20241022",
        cached_usd_per_million=0.08),
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
    """Cost model for estimating LLM API costs with versioning.

    Security features:
    - Pricing registry is frozen after initialization (read-after-init)
    - Integrity hash verified on each pricing access
    - No public mutators after construction
    - Pricing tampering detected and logged
    - Versioned pricing for historical cost accuracy
    """

    def __init__(
        self,
        pricing: Optional[Dict[str, ModelPricing]] = None,
        allow_runtime_updates: bool = False,
        default_version: Optional[PricingVersion] = None,
    ):
        """Initialize with custom pricing or defaults.

        Args:
            pricing: Optional custom pricing dict. Merged with defaults.
            allow_runtime_updates: If True, allows register_model() after init.
                Default False for production security.
            default_version: Default PricingVersion for entries without explicit version.
        """
        # Build pricing registry: defaults + custom (custom overrides)
        merged = {**_DEFAULT_PRICING, **(pricing or {})}

        # Validate all pricing entries
        for key, value in merged.items():
            if not isinstance(value, ModelPricing):
                raise TypeError(f"Pricing for {key} must be ModelPricing instance")
            if value.key != key:
                raise ValueError(f"Pricing key mismatch: {value.key} != {key}")

        # Attach default version to entries without one
        if default_version:
            final_pricing = {}
            for key, value in merged.items():
                if value.version is None:
                    final_pricing[key] = value.with_version(default_version)
                else:
                    final_pricing[key] = value
        else:
            final_pricing = merged

        # Freeze the registry
        self._pricing = MappingProxyType(final_pricing)

        # Compute integrity hash for tamper detection
        self._integrity_hash = self._compute_integrity_hash()
        self._allow_runtime_updates = allow_runtime_updates

        # Version history for historical lookups
        self._version_history: Dict[str, List[ModelPricing]] = {}
        for key, value in final_pricing.items():
            if value.version:
                if key not in self._version_history:
                    self._version_history[key] = []
                self._version_history[key].append(value)
            # Also keep current as latest
            if key not in self._version_history:
                self._version_history[key] = []
            # Ensure current is in history
            current_versions = [v for v in self._version_history[key] if v.version and v.version.effective_to is None]
            if not current_versions:
                self._version_history[key].append(value)

        # Sort history by effective_from
        for key in self._version_history:
            self._version_history[key].sort(key=lambda v: v.version.effective_from if v.version else datetime.min.replace(tzinfo=timezone.utc))

        # Track initialization state
        self._initialized = True

    def _compute_integrity_hash(self) -> str:
        """Compute SHA256 hash of all pricing for integrity verification."""
        sorted_items = sorted(self._pricing.items())
        content = "|".join(
            f"{k}:{v.input_usd_per_million}:{v.output_usd_per_million}:{v.cached_usd_per_million}:{v.reasoning_usd_per_million}"
            for k, v in sorted_items
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _verify_integrity(self) -> bool:
        """Verify pricing registry hasn't been tampered with."""
        current_hash = self._compute_integrity_hash()
        if current_hash != self._integrity_hash:
            logger.critical(
                "PRICING INTEGRITY VIOLATION: Cost model pricing has been modified!",
                extra={
                    "expected_hash": self._integrity_hash[:16],
                    "actual_hash": current_hash[:16],
                },
            )
            return False
        return True

    def get_pricing(self, provider: str, model: str) -> Optional[ModelPricing]:
        """Get current pricing for a provider/model combination.

        Verifies integrity on each access in production mode.
        """
        if not self._verify_integrity():
            pass  # Logged in _verify_integrity

        key = f"{provider}:{model}"
        return self._pricing.get(key)

    def get_pricing_at_version(
        self,
        provider: str,
        model: str,
        version: str,
    ) -> Optional[ModelPricing]:
        """Get pricing for a specific version.

        Args:
            provider: Provider name
            model: Model name
            version: Version string (e.g., "2024.10", "v1.2.3")

        Returns:
            ModelPricing for that version, or None if not found.
        """
        if not self._verify_integrity():
            pass

        key = f"{provider}:{model}"
        history = self._version_history.get(key, [])

        for pricing in history:
            if pricing.version and pricing.version.version == version:
                return pricing

        return None

    def get_pricing_at_timestamp(
        self,
        provider: str,
        model: str,
        timestamp: datetime,
    ) -> Optional[ModelPricing]:
        """Get pricing effective at a specific timestamp.

        For historical cost calculation - finds the pricing version
        that was in effect at the given time.
        """
        if not self._verify_integrity():
            pass

        key = f"{provider}:{model}"
        history = self._version_history.get(key, [])

        # Find the version effective at timestamp
        for pricing in reversed(history):  # Most recent first
            if pricing.version and pricing.version.is_effective_at(timestamp):
                return pricing

        # Fallback to current
        return self.get_pricing(provider, model)

    def estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> Optional[float]:
        """Estimate cost in USD for a request using current pricing.

        Returns None if pricing not available for the model.
        """
        pricing = self.get_pricing(provider, model)
        if not pricing:
            return None
        return pricing.estimate_cost(
            input_tokens, output_tokens, cached_input_tokens, reasoning_tokens
        )

    def estimate_cost_with_version(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        version: str,
        cached_input_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> Optional[float]:
        """Estimate cost using a specific pricing version.

        For historical cost calculation - ensures cost records
        reflect pricing at the time of the request.
        """
        pricing = self.get_pricing_at_version(provider, model, version)
        if not pricing:
            return None
        return pricing.estimate_cost(
            input_tokens, output_tokens, cached_input_tokens, reasoning_tokens
        )

    def estimate_cost_at_timestamp(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        timestamp: datetime,
        cached_input_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> Optional[float]:
        """Estimate cost using pricing effective at timestamp."""
        pricing = self.get_pricing_at_timestamp(provider, model, timestamp)
        if not pricing:
            return None
        return pricing.estimate_cost(
            input_tokens, output_tokens, cached_input_tokens, reasoning_tokens
        )

    def estimate_cost_from_usage(
        self,
        provider: str,
        model: str,
        usage: dict,
    ) -> Optional[float]:
        """Estimate cost from LiteLLM-style usage dict.

        Expected keys: prompt_tokens, completion_tokens, total_tokens
        Also supports: cached_tokens, reasoning_tokens
        """
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("cached_tokens", usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
        reasoning_tokens = usage.get("reasoning_tokens", usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0))
        return self.estimate_cost(provider, model, input_tokens, output_tokens, cached_tokens, reasoning_tokens)

    def estimate_cost_from_usage_with_version(
        self,
        provider: str,
        model: str,
        usage: dict,
        version: str,
    ) -> Optional[float]:
        """Estimate cost from usage dict using specific pricing version."""
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("cached_tokens", usage.get("prompt_tokens_details", {}).get("cached_tokens", 0))
        reasoning_tokens = usage.get("reasoning_tokens", usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0))
        return self.estimate_cost_with_version(provider, model, input_tokens, output_tokens, version, cached_tokens, reasoning_tokens)

    def register_model(self, pricing: ModelPricing) -> None:
        """Register or update pricing for a model.

        SECURITY: Only allowed if allow_runtime_updates=True at construction.
        Raises RuntimeError if called after initialization without permission.
        """
        if not self._allow_runtime_updates:
            raise RuntimeError(
                "CostModel pricing registry is frozen after initialization. "
                "Set allow_runtime_updates=True at construction to enable."
            )

        if not self._verify_integrity():
            raise RuntimeError("Cannot modify pricing: integrity check failed")

        key = pricing.key
        new_registry = dict(self._pricing)
        new_registry[key] = pricing

        # Freeze the updated registry and recompute the integrity hash.
        self._pricing = MappingProxyType(new_registry)
        self._integrity_hash = self._compute_integrity_hash()

        # Maintain version history.
        if pricing.version:
            history = self._version_history.setdefault(key, [])
            if not any(
                v.version and v.version.version == pricing.version.version
                for v in history
            ):
                history.append(pricing)
                history.sort(key=lambda v: v.version.effective_from if v.version else datetime.min.replace(tzinfo=timezone.utc))
        else:
            self._version_history.setdefault(key, [])
            if not self._version_history[key]:
                self._version_history[key].append(pricing)

    def add_historical_version(self, pricing: ModelPricing) -> None:
        """Add a historical pricing version.

        Only allowed with allow_runtime_updates=True.
        Used for backfilling version history.
        """
        if not self._allow_runtime_updates:
            raise RuntimeError("Historical version registration requires allow_runtime_updates=True")

        if not pricing.version:
            raise ValueError("Historical pricing must have a version")

        key = pricing.key
        if key not in self._version_history:
            self._version_history[key] = []
        self._version_history[key].append(pricing)
        self._version_history[key].sort(key=lambda v: v.version.effective_from if v.version else datetime.min.replace(tzinfo=timezone.utc))

    def get_version_history(self, provider: str, model: str) -> List[ModelPricing]:
        """Get all historical pricing versions for a model."""
        key = f"{provider}:{model}"
        return list(self._version_history.get(key, []))

    def get_current_version(self, provider: str, model: str) -> Optional[str]:
        """Get the current pricing version for a model."""
        pricing = self.get_pricing(provider, model)
        if pricing and pricing.version:
            return pricing.version.version
        return None

    def get_all_models(self) -> Dict[str, ModelPricing]:
        """Get all registered model pricing (read-only copy)."""
        if not self._verify_integrity():
            logger.warning("Pricing integrity check failed during get_all_models")
        return dict(self._pricing)

    @property
    def is_frozen(self) -> bool:
        """Whether the pricing registry is frozen (read-only)."""
        return not self._allow_runtime_updates

    @property
    def integrity_hash(self) -> str:
        """Get the integrity hash for external verification."""
        return self._integrity_hash


# Global default cost model instance - created once, frozen
_default_cost_model: Optional[CostModel] = None
_default_model_lock = threading.Lock()


def get_cost_model() -> CostModel:
    """Get the global default cost model (frozen, read-after-init)."""
    global _default_cost_model
    if _default_cost_model is None:
        with _default_model_lock:
            if _default_cost_model is None:
                # Create with default version
                default_version = PricingVersion(
                    version="2024.10",
                    effective_from=datetime(2024, 10, 1, tzinfo=timezone.utc),
                    source="manual",
                    notes="Default pricing as of October 2024",
                )
                _default_cost_model = CostModel(default_version=default_version)
    return _default_cost_model


def set_cost_model(model: CostModel) -> None:
    """Set the global default cost model.

    WARNING: Only for testing or initialization. Replacing the global
    model in production should be done with extreme caution.
    """
    global _default_cost_model
    with _default_model_lock:
        if _default_cost_model is not None:
            logger.warning(
                "Replacing global cost model - ensure this is intentional",
                extra={
                    "old_hash": _default_cost_model.integrity_hash[:16],
                    "new_hash": model.integrity_hash[:16],
                },
            )
        _default_cost_model = model


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> Optional[float]:
    """Convenience function to estimate cost using default model."""
    return get_cost_model().estimate_cost(
        provider, model, input_tokens, output_tokens, cached_input_tokens, reasoning_tokens
    )


__all__ = [
    "PricingVersion",
    "ModelPricing",
    "CostModel",
    "get_cost_model",
    "set_cost_model",
    "estimate_cost",
]
