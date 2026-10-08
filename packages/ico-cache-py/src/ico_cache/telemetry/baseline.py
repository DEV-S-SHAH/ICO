"""Baseline calculation for token savings measurement.

Compares actual token usage against a counterfactual baseline (no cache / no ICO-Cache)
to compute avoided tokens and cost savings. Ensures fair comparison by holding
model, provider, generation config, and prompt/context constant.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time

from .provider_adapters import UsageInfo, UsageSource, get_provider_registry


class BaselineStrategy(str, Enum):
    """Strategy for calculating baseline token usage."""
    WITHOUT_CACHE = "without_cache"          # Full LLM call, no cache at all
    WITH_ICO_CACHE = "with_ico_cache"        # With ICO-Cache but no reuse decision


@dataclass(frozen=True)
class BaselineUsage:
    """Token usage for a baseline scenario."""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    strategy: BaselineStrategy = BaselineStrategy.WITHOUT_CACHE
    model: str = ""
    provider: str = ""
    generation_config_hash: str = ""
    prompt_hash: str = ""
    context_hash: str = ""
    estimated_cost_usd: Optional[float] = None
    pricing_version: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "strategy": self.strategy.value,
            "model": self.model,
            "provider": self.provider,
            "generation_config_hash": self.generation_config_hash,
            "prompt_hash": self.prompt_hash,
            "context_hash": self.context_hash,
            "estimated_cost_usd": self.estimated_cost_usd,
            "pricing_version": self.pricing_version,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class AvoidedUsage:
    """Token usage avoided by cache reuse."""
    input_tokens_avoided: int
    output_tokens_avoided: int
    total_tokens_avoided: int
    cached_input_tokens_avoided: int = 0
    reasoning_tokens_avoided: int = 0
    cost_usd_avoided: Optional[float] = None
    savings_pct: float = 0.0
    baseline: Optional[BaselineUsage] = None
    actual: Optional[UsageInfo] = None
    action: str = ""
    layer: str = ""
    confidence: float = 0.0
    decision_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens_avoided": self.input_tokens_avoided,
            "output_tokens_avoided": self.output_tokens_avoided,
            "total_tokens_avoided": self.total_tokens_avoided,
            "cached_input_tokens_avoided": self.cached_input_tokens_avoided,
            "reasoning_tokens_avoided": self.reasoning_tokens_avoided,
            "cost_usd_avoided": self.cost_usd_avoided,
            "savings_pct": self.savings_pct,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "actual": self.actual.to_dict() if self.actual else None,
            "action": self.action,
            "layer": self.layer,
            "confidence": self.confidence,
            "decision_id": self.decision_id,
        }


@dataclass
class DecisionContext:
    """Context for baseline calculation (simplified from decision_engine)."""
    query: str
    context: Optional[str] = None
    prompt_template: Optional[str] = None
    prompt_version: str = "v1"
    model: str = "gpt-4o"
    provider: str = "openai"
    model_params: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tenant_id: str = "default"
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    repo_url: Optional[str] = None
    commit_sha: Optional[str] = None
    changed_files: List[str] = field(default_factory=list)
    available_tools: List[Any] = field(default_factory=list)
    tool_versions: Dict[str, str] = field(default_factory=dict)
    personalized_response: bool = False
    injected_context_hash: Optional[str] = None
    authz_version: str = "v1"
    reuse_policy: Any = None
    max_latency_ms: int = 5000
    cost_budget_usd: Optional[float] = None

    def __post_init__(self):
        # Compute derived fields for fingerprinting
        self.model_fingerprint = self._compute_model_fingerprint()
        self.params_hash = self._compute_params_hash()

    def _compute_model_fingerprint(self) -> str:
        import hashlib
        deterministic_params = {
            k: v for k, v in self.model_params.items()
            if k in ("temperature", "top_p", "top_k", "max_tokens", "seed")
        }
        parts = [self.model, self.provider, str(sorted(deterministic_params.items()))]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _compute_params_hash(self) -> str:
        import hashlib
        raw = str(sorted(self.model_params.items()))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get_prompt_hash(self) -> str:
        """Hash of the full prompt that would be sent to LLM."""
        import hashlib
        parts = [
            self.query,
            self.context or "",
            self.prompt_template or "",
            self.prompt_version,
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get_context_hash(self) -> str:
        """Hash of context."""
        import hashlib
        if not self.context or not self.context.strip():
            return "empty"
        return hashlib.sha256(self.context.encode()).hexdigest()[:16]

    def get_generation_config_hash(self) -> str:
        """Hash of generation config (model + params)."""
        import hashlib
        det_params = {
            k: v for k, v in self.model_params.items()
            if k in ("temperature", "top_p", "top_k", "max_tokens", "seed", "stop")
        }
        parts = [self.model, self.provider, str(sorted(det_params.items()))]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class BaselineCalculator:
    """Calculates baseline token usage and avoided usage from cache hits."""

    def __init__(
        self,
        cost_model=None,
        default_output_tokens: int = 500,
    ):
        """Initialize baseline calculator.

        Args:
            cost_model: Optional CostModel instance for cost estimation
            default_output_tokens: Default output tokens for estimation when unknown
        """
        self._cost_model = cost_model
        self._default_output_tokens = default_output_tokens
        self._provider_registry = get_provider_registry()

    def calculate_baseline_usage(
        self,
        ctx: DecisionContext,
        generation_result: Optional[Dict[str, Any]] = None,
        strategy: BaselineStrategy = BaselineStrategy.WITHOUT_CACHE,
    ) -> BaselineUsage:
        """Calculate baseline token usage for a request.

        For WITHOUT_CACHE strategy, uses actual generation result if available,
        otherwise estimates from context. For WITH_ICO_CACHE strategy, assumes
        the cache layer was checked but missed, so full generation occurs.

        Args:
            ctx: Decision context with query, model, params
            generation_result: Actual LLM response (for WITHOUT_CACHE with real data)
            strategy: Baseline strategy to use

        Returns:
            BaselineUsage with estimated or actual token counts
        """
        # Extract generation config hash
        gen_config_hash = ctx.get_generation_config_hash()
        prompt_hash = ctx.get_prompt_hash()
        context_hash = ctx.get_context_hash()

        # Determine provider/model
        provider = ctx.provider
        model = ctx.model

        if generation_result:
            # Use actual generation result
            usage_info = self._provider_registry.extract_usage(provider, generation_result)
            input_tokens = usage_info.input_tokens
            output_tokens = usage_info.output_tokens
            total_tokens = usage_info.total_tokens
            cached_input = usage_info.cached_input_tokens
            reasoning = usage_info.reasoning_tokens
            _usage_source = usage_info.usage_source
        else:
            # Estimate from context
            input_tokens, output_tokens = self._estimate_tokens_from_context(ctx)
            total_tokens = input_tokens + output_tokens
            cached_input = 0
            reasoning = 0
            _usage_source = UsageSource.ESTIMATED

        # Estimate cost if cost model available
        estimated_cost = None
        pricing_version = None
        if self._cost_model:
            estimated_cost = self._cost_model.estimate_cost(
                provider, model, input_tokens, output_tokens
            )
            # Try to get pricing version
            pricing = self._cost_model.get_pricing(provider, model)
            if pricing and hasattr(pricing, 'version'):
                pricing_version = pricing.version

        return BaselineUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input,
            reasoning_tokens=reasoning,
            strategy=strategy,
            model=model,
            provider=provider,
            generation_config_hash=gen_config_hash,
            prompt_hash=prompt_hash,
            context_hash=context_hash,
            estimated_cost_usd=estimated_cost,
            pricing_version=pricing_version,
        )

    def _estimate_tokens_from_context(self, ctx: DecisionContext) -> tuple[int, int]:
        """Estimate input/output tokens from context.

        Uses character-based heuristic (~4 chars/token) as fallback.
        """
        # Estimate input tokens from query + context + prompt template
        input_chars = len(ctx.query)
        if ctx.context:
            input_chars += len(ctx.context)
        if ctx.prompt_template:
            input_chars += len(ctx.prompt_template)

        # Add overhead for system prompt, formatting
        input_chars += 500  # approximate system prompt overhead

        input_tokens = max(1, input_chars // 4)

        # Estimate output tokens from max_tokens param or default
        output_tokens = ctx.model_params.get("max_tokens", self._default_output_tokens)
        if isinstance(output_tokens, str):
            try:
                output_tokens = int(output_tokens)
            except ValueError:
                output_tokens = self._default_output_tokens

        return input_tokens, output_tokens

    def calculate_avoided_usage(
        self,
        actual_usage: UsageInfo,
        baseline: BaselineUsage,
        action: str = "",
        layer: str = "",
        confidence: float = 0.0,
        decision_id: str = "",
    ) -> AvoidedUsage:
        """Calculate avoided usage by comparing actual vs baseline.

        Only valid when baseline and actual share:
        - Same model
        - Same provider
        - Same generation config
        - Same prompt/context (or actual is from cache hit with 0 LLM tokens)

        Args:
            actual_usage: Actual token usage (may be 0 for cache hits)
            baseline: Baseline usage for comparison
            action: Reuse action (e.g., EXACT_REUSE, SEMANTIC_REUSE)
            layer: Cache layer that produced the hit
            confidence: Reuse confidence
            decision_id: Decision ID for tracing

        Returns:
            AvoidedUsage with token and cost savings
        """
        # Validate compatibility
        self._validate_compatibility(actual_usage, baseline)

        input_avoided = baseline.input_tokens - actual_usage.input_tokens
        output_avoided = baseline.output_tokens - actual_usage.output_tokens
        total_avoided = baseline.total_tokens - actual_usage.total_tokens
        cached_avoided = baseline.cached_input_tokens - actual_usage.cached_input_tokens
        reasoning_avoided = baseline.reasoning_tokens - actual_usage.reasoning_tokens

        # Clamp to non-negative (actual shouldn't exceed baseline for cache hits)
        input_avoided = max(0, input_avoided)
        output_avoided = max(0, output_avoided)
        total_avoided = max(0, total_avoided)
        cached_avoided = max(0, cached_avoided)
        reasoning_avoided = max(0, reasoning_avoided)

        # Calculate cost savings
        cost_avoided = None
        if baseline.estimated_cost_usd is not None:
            # Estimate actual cost
            actual_cost = None
            if self._cost_model:
                actual_cost = self._cost_model.estimate_cost(
                    actual_usage.provider, actual_usage.model,
                    actual_usage.input_tokens, actual_usage.output_tokens
                )
            if actual_cost is not None:
                cost_avoided = baseline.estimated_cost_usd - actual_cost
            else:
                # Proportional estimate
                if baseline.total_tokens > 0:
                    cost_avoided = baseline.estimated_cost_usd * (total_avoided / baseline.total_tokens)

        # Savings percentage
        savings_pct = 0.0
        if baseline.total_tokens > 0:
            savings_pct = total_avoided / baseline.total_tokens

        return AvoidedUsage(
            input_tokens_avoided=input_avoided,
            output_tokens_avoided=output_avoided,
            total_tokens_avoided=total_avoided,
            cached_input_tokens_avoided=cached_avoided,
            reasoning_tokens_avoided=reasoning_avoided,
            cost_usd_avoided=cost_avoided,
            savings_pct=savings_pct,
            baseline=baseline,
            actual=actual_usage,
            action=action,
            layer=layer,
            confidence=confidence,
            decision_id=decision_id,
        )

    def _validate_compatibility(self, actual: UsageInfo, baseline: BaselineUsage) -> None:
        """Validate that actual and baseline are comparable.

        Raises:
            ValueError: If model, provider, or generation config differ
        """
        if actual.provider and actual.provider != baseline.provider:
            raise ValueError(
                f"Provider mismatch: actual={actual.provider}, baseline={baseline.provider}"
            )
        if actual.model and actual.model != baseline.model:
            raise ValueError(
                f"Model mismatch: actual={actual.model}, baseline={baseline.model}"
            )
        # Note: We don't validate prompt_hash because for cache hits,
        # the actual usage may be 0 (no LLM call) while baseline has full tokens

    def calculate_batch_avoided(
        self,
        actual_usages: List[UsageInfo],
        baselines: List[BaselineUsage],
        actions: List[str],
        layers: List[str],
        confidences: List[float],
        decision_ids: List[str],
    ) -> List[AvoidedUsage]:
        """Calculate avoided usage for a batch of requests."""
        if not (len(actual_usages) == len(baselines) == len(actions) == len(layers) == len(confidences) == len(decision_ids)):
            raise ValueError("All input lists must have the same length")

        return [
            self.calculate_avoided_usage(
                actual_usages[i], baselines[i], actions[i], layers[i], confidences[i], decision_ids[i]
            )
            for i in range(len(actual_usages))
        ]

    def aggregate_savings(self, avoided_list: List[AvoidedUsage]) -> Dict[str, Any]:
        """Aggregate savings across multiple requests."""
        if not avoided_list:
            return {
                "total_input_avoided": 0,
                "total_output_avoided": 0,
                "total_tokens_avoided": 0,
                "total_cost_avoided_usd": 0.0,
                "avg_savings_pct": 0.0,
                "count": 0,
            }

        total_input = sum(a.input_tokens_avoided for a in avoided_list)
        total_output = sum(a.output_tokens_avoided for a in avoided_list)
        total_tokens = sum(a.total_tokens_avoided for a in avoided_list)
        total_cached = sum(a.cached_input_tokens_avoided for a in avoided_list)
        total_reasoning = sum(a.reasoning_tokens_avoided for a in avoided_list)

        cost_avoided = sum(a.cost_usd_avoided or 0.0 for a in avoided_list)
        avg_savings = sum(a.savings_pct for a in avoided_list) / len(avoided_list)

        # By action
        by_action: Dict[str, Dict[str, Any]] = {}
        for a in avoided_list:
            if a.action not in by_action:
                by_action[a.action] = {"count": 0, "tokens_avoided": 0, "cost_avoided": 0.0}
            by_action[a.action]["count"] += 1
            by_action[a.action]["tokens_avoided"] += a.total_tokens_avoided
            by_action[a.action]["cost_avoided"] += a.cost_usd_avoided or 0.0

        # By layer
        by_layer: Dict[str, Dict[str, Any]] = {}
        for a in avoided_list:
            if a.layer not in by_layer:
                by_layer[a.layer] = {"count": 0, "tokens_avoided": 0, "cost_avoided": 0.0}
            by_layer[a.layer]["count"] += 1
            by_layer[a.layer]["tokens_avoided"] += a.total_tokens_avoided
            by_layer[a.layer]["cost_avoided"] += a.cost_usd_avoided or 0.0

        return {
            "total_input_avoided": total_input,
            "total_output_avoided": total_output,
            "total_tokens_avoided": total_tokens,
            "total_cached_avoided": total_cached,
            "total_reasoning_avoided": total_reasoning,
            "total_cost_avoided_usd": round(cost_avoided, 6),
            "avg_savings_pct": round(avg_savings * 100, 2),
            "count": len(avoided_list),
            "by_action": by_action,
            "by_layer": by_layer,
        }


__all__ = [
    "BaselineStrategy",
    "BaselineUsage",
    "AvoidedUsage",
    "DecisionContext",
    "BaselineCalculator",
]
