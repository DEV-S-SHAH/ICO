import requests

DEFAULT_TIMEOUT = 10.0


class IcoCache:
    def __init__(self, base_url="http://localhost:8000", semantic_threshold=0.92, timeout=DEFAULT_TIMEOUT):
        self.base_url = base_url
        self.semantic_threshold = semantic_threshold
        self.timeout = timeout

    def resolve(self, query: str, context: str, callback):
        resp = requests.post(
            f"{self.base_url}/resolve",
            json={"query": query, "context": context},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("source") != "MISS":
            return payload.get("response")

        generated = callback()
        requests.post(
            f"{self.base_url}/ingest",
            json={"query": query, "context": context, "response": generated},
            timeout=self.timeout,
        )
        return generated


def ico_cache(base_url="http://localhost:8000", semantic_threshold=0.92, timeout=DEFAULT_TIMEOUT):
    return IcoCache(base_url, semantic_threshold, timeout)
