import redis
from typing import Optional
from ..base import BaseExactStore

class RedisStore(BaseExactStore):
    def __init__(self, host: str = "localhost", port: int = 6379, password: str = None):
        self.r = redis.Redis(host=host, port=port, password=password)

    def get(self, key: str) -> Optional[bytes]:
        return self.r.get(key)

    def set(self, key: str, value: bytes, ex: Optional[int] = None):
        self.r.set(key, value, ex=ex)
