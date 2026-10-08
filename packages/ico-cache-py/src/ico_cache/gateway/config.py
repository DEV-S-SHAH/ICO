"""Configuration for the OpenAI-compatible gateway."""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ProviderConfig:
    """Configuration for an upstream LLM provider."""

    name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = 30.0
    max_retries: int = 3


@dataclass
class GatewayConfig:
    """Configuration for the ICO-Cache OpenAI-compatible gateway."""

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080

    # ICO-Cache backend settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # Cache settings
    semantic_threshold: float = 0.85
    adaptive_threshold: bool = True
    target_hit_rate: float = 0.80

    # Provider configurations
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

    # Observability
    log_level: str = "INFO"
    log_json: bool = False
    otel_service_name: str = "ico-cache-gateway"
    otel_exporter_otlp_endpoint: Optional[str] = None

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """Create configuration from environment variables."""
        providers = {}

        # OpenAI
        if os.getenv("OPENAI_API_KEY"):
            providers["openai"] = ProviderConfig(
                name="openai",
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                timeout=float(os.getenv("OPENAI_TIMEOUT", "30.0")),
            )

        # Anthropic
        if os.getenv("ANTHROPIC_API_KEY"):
            providers["anthropic"] = ProviderConfig(
                name="anthropic",
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                timeout=float(os.getenv("ANTHROPIC_TIMEOUT", "30.0")),
            )

        # Google (Gemini)
        if os.getenv("GOOGLE_API_KEY"):
            providers["google"] = ProviderConfig(
                name="google",
                api_key=os.getenv("GOOGLE_API_KEY"),
                base_url=os.getenv("GOOGLE_BASE_URL"),
                timeout=float(os.getenv("GOOGLE_TIMEOUT", "30.0")),
            )

        return cls(
            host=os.getenv("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.getenv("GATEWAY_PORT", "8080")),
            redis_host=os.getenv("REDIS_HOST", "localhost"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            redis_password=os.getenv("REDIS_PASSWORD"),
            qdrant_host=os.getenv("QDRANT_HOST", "localhost"),
            qdrant_port=int(os.getenv("QDRANT_PORT", "6333")),
            semantic_threshold=float(os.getenv("SEMANTIC_THRESHOLD", "0.85")),
            adaptive_threshold=os.getenv("ADAPTIVE_THRESHOLD", "true").lower() == "true",
            target_hit_rate=float(os.getenv("TARGET_HIT_RATE", "0.80")),
            providers=providers,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_json=os.getenv("LOG_JSON", "false").lower() == "true",
            otel_service_name=os.getenv("OTEL_SERVICE_NAME", "ico-cache-gateway"),
            otel_exporter_otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
        )
