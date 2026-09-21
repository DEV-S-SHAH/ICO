"""Data ingestion utility to fetch real-world knowledge datasets from the web."""

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

TOPICS = [
    "Artificial_intelligence",
    "Machine_learning",
    "Large_language_model",
    "Retrieval-augmented_generation",
    "Quantum_computing",
]

HEADERS = {"User-Agent": "RAG-LangGraph-Demo/1.0 (educational/research project)"}


def download_knowledge_dataset(output_dir: str = "data/dataset") -> List[Dict[str, str]]:
    """Download articles from Wikipedia API and save them as local text & JSON."""
    os.makedirs(output_dir, exist_ok=True)
    documents = []

    for topic in TOPICS:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                title = payload.get("title", topic.replace("_", " "))
                extract = payload.get("extract", "")
                page_url = payload.get("content_urls", {}).get("desktop", {}).get("page", "")

                doc = {
                    "id": topic,
                    "title": title,
                    "content": extract,
                    "url": page_url,
                }
                documents.append(doc)

                file_path = os.path.join(output_dir, f"{topic}.json")
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2)
                
                txt_path = os.path.join(output_dir, f"{topic}.txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(f"Title: {title}\nURL: {page_url}\n\n{extract}")

                print(f"[Dataset] Downloaded & indexed: {title} ({len(extract)} chars)")
        except Exception as e:
            print(f"[Dataset] Warning: Failed to download {topic}: {e}")

    summary_file = os.path.join(output_dir, "corpus.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2)

    return documents


if __name__ == "__main__":
    docs = download_knowledge_dataset()
    print(f"Total documents downloaded: {len(docs)}")
