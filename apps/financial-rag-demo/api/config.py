import json
import sys
from typing import Optional
from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

# Environments where it is acceptable to run without configured API keys.
_DEV_ENVIRONMENTS = {"development", "dev", "local", "test"}


def parse_api_keys(raw) -> dict[str, str]:
    """Parse the API_KEYS env var into an api_key -> tenant_id map.

    Accepts a JSON object or a comma-separated ``key:tenant`` list. Parsing is
    done here (not by pydantic-settings) so malformed input yields a clean
    config error instead of an opaque SettingsError.
    """
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return {str(k): str(v) for k, v in parsed.items()}
    mapping = {}
    for pair in raw.split(","):
        if ":" in pair:
            k, t = pair.strip().split(":", 1)
            mapping[k.strip()] = t.strip()
    return mapping


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # API & Server Configuration
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # Redis Backend
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_auth: str = Field(default="myredissecret", alias="REDIS_AUTH")
    redis_url: Optional[str] = Field(default=None, alias="REDIS_URL")

    # Qdrant Backend
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_url: Optional[str] = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: Optional[str] = Field(default=None, alias="QDRANT_API_KEY")

    # LLM (Google Gemini, called through LiteLLM)
    llm_model: str = Field(default="gemini/gemini-flash-latest", alias="LLM_MODEL")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    llm_timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")

    # Langfuse
    langfuse_host: str = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")

    # Auth & Multi-Tenancy (api_key -> tenant_id)
    # Stored as a raw string so pydantic-settings never JSON-decodes it; the
    # `api_keys` property parses it. No default credentials: an empty map
    # rejects every request (fail closed).
    api_keys_raw: str = Field(default="", alias="API_KEYS")

    # Ingestion security: client-supplied file paths are confined to this root.
    ingest_root_dir: str = Field(default="/app/data/ingest", alias="INGEST_ROOT_DIR")
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")

    # Universal document loaders / OCR (applies to any file type)
    ocr_enabled: bool = Field(default=True, alias="OCR_ENABLED")
    ocr_languages: str = Field(default="eng", alias="OCR_LANGUAGES")
    ocr_dpi: int = Field(default=200, alias="OCR_DPI")

    # Distributed rate limiting (memory:// or a redis:// / redis+ssl:// URI)
    rate_limit_storage_uri: Optional[str] = Field(default=None, alias="RATE_LIMIT_STORAGE_URI")
    rate_limit_default: str = Field(default="1000/minute", alias="RATE_LIMIT_DEFAULT")

    # Observability
    otel_exporter_otlp_endpoint: Optional[str] = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field(default="ico-cache-api", alias="OTEL_SERVICE_NAME")
    log_json: bool = Field(default=True, alias="LOG_JSON")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def resolved_rate_limit_storage_uri(self) -> str:
        """Redis-backed distributed limiter in production, in-memory in dev."""
        if self.rate_limit_storage_uri:
            return self.rate_limit_storage_uri
        if self.environment.lower() in _DEV_ENVIRONMENTS:
            return "memory://"
        if self.redis_url:
            return self.redis_url
        auth = f":{self.redis_auth}@" if self.redis_auth else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/0"


    @property
    def api_keys(self) -> dict[str, str]:
        return parse_api_keys(self.api_keys_raw)

    @model_validator(mode="after")
    def _require_api_keys_outside_dev(self):
        if not self.api_keys and self.environment.lower() not in _DEV_ENVIRONMENTS:
            raise ValueError(
                "API_KEYS must be set when ENVIRONMENT is not a development environment."
            )
        return self



def get_settings() -> Settings:
    try:
        return Settings()
    except (ValidationError, SettingsError) as e:
        print(f"FATAL CONFIG ERROR: Required environment variables are missing or invalid:\n{e}", file=sys.stderr)
        raise SystemExit(1) from e


settings = get_settings()
