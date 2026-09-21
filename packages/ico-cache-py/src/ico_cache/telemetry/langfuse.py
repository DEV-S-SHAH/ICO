"""Optional Langfuse exporter used to trace RAG generation calls.

Initialization is best-effort: when credentials are absent or the SDK/endpoint
is unavailable the exporter returns ``None`` and the pipeline runs untouched.
"""
import logging
from contextlib import contextmanager
from typing import Any, Optional

logger = logging.getLogger("ico_cache.telemetry.langfuse")


class _GenerationRecorder:
    """No-op-safe handle returned by ``LangfuseExporter.generation``."""

    def __init__(self, observation: Optional[Any]):
        self._observation = observation

    def update(self, **kwargs: Any) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(**kwargs)
        except Exception:  # pragma: no cover - never break generation
            logger.debug("langfuse observation update failed", exc_info=True)


class LangfuseExporter:
    def __init__(self, client: Any):
        self.client = client

    @contextmanager
    def generation(self, name: str, model: str, prompt: str):
        observation = None
        try:
            observation = self.client.start_as_current_observation(
                name=name, as_type="generation", model=model, input=prompt
            )
            observation.__enter__()
        except Exception as e:  # pragma: no cover - depends on SDK/collector
            logger.warning("Langfuse generation span failed: %s", e)
            observation = None

        recorder = _GenerationRecorder(observation)
        try:
            yield recorder
        finally:
            if observation is not None:
                try:
                    observation.__exit__(None, None, None)
                except Exception:  # pragma: no cover
                    logger.debug("langfuse observation exit failed", exc_info=True)

    def flush(self) -> None:
        try:
            self.client.flush()
        except Exception:  # pragma: no cover
            logger.debug("langfuse flush failed", exc_info=True)


def init_langfuse(
    host: Optional[str] = None,
    public_key: Optional[str] = None,
    secret_key: Optional[str] = None,
) -> Optional[LangfuseExporter]:
    if not public_key or not secret_key:
        return None
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("langfuse not installed; Langfuse tracing disabled")
        return None
    try:
        client = Langfuse(host=host, public_key=public_key, secret_key=secret_key)
        logger.info("Langfuse tracing enabled")
        return LangfuseExporter(client)
    except Exception as e:  # pragma: no cover - depends on connectivity/credentials
        logger.warning("Failed to initialize Langfuse: %s", e)
        return None
