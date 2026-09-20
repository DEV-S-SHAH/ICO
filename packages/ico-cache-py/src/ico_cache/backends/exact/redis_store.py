import redis
from typing import Optional
from ..base import BaseExactStore

class RedisStore(BaseExactStore):
    def __init__(self, host: str = "localhost", port: int = 6379, password: str = None):
        self.r = redis.Redis(host=host, port=port, password=password)

    @property
    def client(self):
        return self.r

    def get(self, key: str) -> Optional[bytes]:
        return self.r.get(key)

    def set(self, key: str, value: bytes, ex: Optional[int] = None):
        self.r.set(key, value, ex=ex)

    def delete(self, key: str) -> bool:
        return bool(self.r.delete(key))

    def delete_prefix(self, prefix: str) -> int:
        cursor = 0
        deleted = 0
        match_pattern = f"{prefix}*"
        while True:
            cursor, keys = self.r.scan(cursor=cursor, match=match_pattern, count=100)
            if keys:
                deleted += self.r.delete(*keys)
            if cursor == 0:
                break
        return deleted

    def xadd(self, stream: str, fields: dict) -> str:
        res = self.r.xadd(stream, fields)
        return res.decode() if isinstance(res, bytes) else str(res)

    def xread(self, streams: dict, count: Optional[int] = None, block: Optional[int] = None):
        return self.r.xread(streams, count=count, block=block)

