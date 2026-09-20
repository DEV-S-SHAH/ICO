import sys
from typing import Optional
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Ollama LLM
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="qwen2.5:3b", alias="OLLAMA_MODEL")

    # Langfuse
    langfuse_host: str = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")


def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        print(f"FATAL CONFIG ERROR: Required environment variables are missing or invalid:\n{e}", file=sys.stderr)
        raise SystemExit(1) from e


settings = get_settings()
