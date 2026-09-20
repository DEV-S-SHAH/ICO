import requests

class IcoCache:
    def __init__(self, base_url="http://localhost:8000", semantic_threshold=0.92):
        self.base_url = base_url
        self.semantic_threshold = semantic_threshold

    def resolve(self, query: str, context: str, callback):
        resp = requests.post(f"{self.base_url}/resolve", json={"query": query, "context": context}).json()
        if resp.get("source") != "MISS":
            return resp.get("response")

        # MISS
        generated = callback()

        requests.post(f"{self.base_url}/ingest", json={"query": query, "context": context, "response": generated})
        return generated

def ico_cache(base_url="http://localhost:8000", semantic_threshold=0.92):
    return IcoCache(base_url, semantic_threshold)
