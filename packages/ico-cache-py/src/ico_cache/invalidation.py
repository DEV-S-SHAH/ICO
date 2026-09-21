import json
import logging
import asyncio
import os
import signal
import sys
import threading
import time
from typing import Callable, Optional
from .core.cache_engine import CacheEngine
from .backends.base import BaseExactStore

logger = logging.getLogger("ico_cache.invalidation")


def publish_invalidation(
    exact_store: BaseExactStore,
    tenant_id: str = "default",
    filter_dict: Optional[dict] = None,
    stream: str = "cache_invalidation",
) -> Optional[str]:
    """
    Publishes an invalidation event to Redis Streams.
    """
    if hasattr(exact_store, "xadd"):
        payload = {
            "tenant_id": tenant_id,
            "filter": json.dumps(filter_dict or {}),
        }
        return exact_store.xadd(stream, payload)
    return None


class InvalidationWorker:
    """
    Background worker that consumes invalidation events from Redis Streams
    and applies them to the CacheEngine.
    """

    def __init__(
        self,
        engine: CacheEngine,
        stream_name: str = "cache_invalidation",
        group_name: str = "ico_invalidation_group",
        consumer_name: str = "invalidation_worker_1",
    ):
        self.engine = engine
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_id = "0-0"
        # Updated on every loop iteration; used by the liveness/readiness probe.
        self.last_heartbeat = time.time()

    async def process_event(self, tenant_id: str, filter_dict: Optional[dict] = None) -> dict:
        """Process an invalidation event on the engine."""
        return await self.engine.invalidate(tenant_id=tenant_id, filter_dict=filter_dict)

    async def run_once(self, count: int = 10, block: int = 100) -> int:
        """
        Polls the Redis stream once, processes events, and returns the number of events processed.
        """
        exact_store = self.engine.exact_store
        if not hasattr(exact_store, "xread"):
            return 0

        try:
            entries = exact_store.xread({self.stream_name: self._last_id}, count=count, block=block)
            if not entries:
                return 0

            processed_count = 0
            for stream_name, messages in entries:
                for msg_id, data in messages:
                    # decode msg_id
                    mid = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                    self._last_id = mid

                    tenant_id = data.get(b"tenant_id", b"default")
                    if isinstance(tenant_id, bytes):
                        tenant_id = tenant_id.decode()
                    filter_raw = data.get(b"filter", b"{}")
                    if isinstance(filter_raw, bytes):
                        filter_raw = filter_raw.decode()
                    try:
                        filter_dict = json.loads(filter_raw)
                    except Exception:
                        filter_dict = {}

                    await self.process_event(tenant_id=tenant_id, filter_dict=filter_dict)
                    processed_count += 1
            return processed_count
        except Exception as e:
            logger.warning(f"Error reading from Redis stream: {e}")
            return 0

    async def start(self, poll_interval: float = 0.5):
        """Start the background consumer loop."""
        self._running = True
        while self._running:
            self.last_heartbeat = time.time()
            try:
                await self.run_once(count=20, block=200)
            except Exception as e:
                logger.error(f"Error in InvalidationWorker loop: {e}")
            await asyncio.sleep(poll_interval)

    def stop(self):
        """Stop the background consumer loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()


class _HealthServer:
    """Minimal HTTP probe server for the worker (liveness/readiness)."""

    def __init__(self, port: int, heartbeat: Callable[[], float], max_age: float = 30.0):
        self.port = port
        self.heartbeat = heartbeat
        self.max_age = max_age
        self._httpd = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        heartbeat = self.heartbeat
        max_age = self.max_age

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (stdlib naming)
                alive = (time.time() - heartbeat()) < max_age
                payload = json.dumps({"status": "ok" if alive else "stalled"}).encode()
                self.send_response(200 if alive else 503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # silence per-request access logs
                return

        httpd = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()


def _build_engine() -> CacheEngine:
    from .backends.embedding.fastembed_embedder import FastEmbedder
    from .backends.exact.redis_store import RedisStore
    from .backends.vector.qdrant_store import QdrantStore

    return CacheEngine(
        embedder=FastEmbedder(),
        vector_store=QdrantStore(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
        ),
        exact_store=RedisStore(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_AUTH") or None,
        ),
        tenant_isolation_mode=os.getenv("TENANT_ISOLATION_MODE", "collection"),
    )


def main() -> int:
    """Entry point for the standalone invalidation worker container."""
    from .telemetry.logging import configure_logging

    configure_logging(
        json_logs=os.getenv("LOG_JSON", "true").strip().lower() not in {"0", "false", "no", "off"},
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    engine = _build_engine()
    worker = InvalidationWorker(
        engine,
        stream_name=os.getenv("INVALIDATION_STREAM", "cache_invalidation"),
        group_name=os.getenv("INVALIDATION_GROUP", "ico_invalidation_group"),
        consumer_name=os.getenv("INVALIDATION_CONSUMER", f"worker-{os.getpid()}"),
    )

    health: Optional[_HealthServer] = None
    if os.getenv("WORKER_HEALTH_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}:
        try:
            health = _HealthServer(
                port=int(os.getenv("WORKER_HEALTH_PORT", "8081")),
                heartbeat=lambda: worker.last_heartbeat,
            )
            health.start()
            logger.info("worker health probe listening on port %s", health.port)
        except OSError as e:
            logger.warning("could not start worker health server: %s", e)
            health = None

    def _handle_signal(signum, _frame):
        logger.info("received signal %s; shutting down", signum)
        worker.stop()

    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, OSError):
            pass
    if hasattr(signal, "SIGINT"):
        try:
            signal.signal(signal.SIGINT, _handle_signal)
        except (ValueError, OSError):
            pass

    logger.info("invalidation worker starting")
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:  # pragma: no cover
        worker.stop()
    finally:
        if health is not None:
            health.stop()
    logger.info("invalidation worker stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
