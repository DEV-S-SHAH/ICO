import sqlite3
from typing import Optional
from ..base import BaseExactStore

class SQLiteStore(BaseExactStore):
    def __init__(self, db_path: str = "cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS cache
                            (key TEXT PRIMARY KEY, value BLOB)''')

    def get(self, key: str) -> Optional[bytes]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM cache WHERE key=?", (key,))
            row = cursor.fetchone()
            if row:
                return row[0]
            return None

    def set(self, key: str, value: bytes, ex: Optional[int] = None):
        # Note: SQLite store doesn't support TTL out of the box in this simple implementation
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, value))

    def delete(self, key: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            return cur.rowcount > 0

    def delete_prefix(self, prefix: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM cache WHERE key LIKE ?", (f"{prefix}%",))
            return cur.rowcount

