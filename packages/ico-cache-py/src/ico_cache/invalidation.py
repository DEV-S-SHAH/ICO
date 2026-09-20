import json
import logging
import asyncio
from typing import Optional, Any
from .core.cache_engine import CacheEngine
from .backends.base import BaseExactStore
from .backends.exact.redis_store import RedisStore

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
