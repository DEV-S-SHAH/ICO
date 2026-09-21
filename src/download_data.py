"""Multi-format Dataset Downloader & Parser (PDF, TXT, JSON)."""

import io
import json
import logging
import os
import urllib.request
from typing import Dict, List
import pypdf

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

PDF_SOURCES = [
    {
        "id": "transformer_paper",
        "title": "Attention Is All You Need (Vaswani et al.)",
        "url": "https://arxiv.org/pdf/1706.03762",
        "max_pages": 5,
    }
]

TXT_WIKI_TOPICS = [
    "Artificial_intelligence",
    "Machine_learning",
    "Large_language_model",
    "Retrieval-augmented_generation",
    "Quantum_computing",
    "Deep_learning",
    "Natural_language_processing",
]


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Break large text into overlapping windows."""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_size]
        chunks.append(" ".join(chunk_words))
        if i + chunk_size >= len(words):
            break
        i += chunk_size - overlap
    return chunks


def download_and_prepare_dataset(output_dir: str = "data/complex_dataset") -> List[Dict[str, str]]:
    """Download PDF research papers and TXT articles, parse chunks, and compile corpus."""
    os.makedirs(output_dir, exist_ok=True)
    pdf_dir = os.path.join(output_dir, "pdfs")
    txt_dir = os.path.join(output_dir, "txts")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(txt_dir, exist_ok=True)

    chunks = []

    # 1. Download & Parse PDF
    print("\n--- 1. Downloading & Parsing Complex PDF Documents ---")
    for item in PDF_SOURCES:
        pdf_path = os.path.join(pdf_dir, f"{item['id']}.pdf")
        if not os.path.exists(pdf_path):
            print(f"Downloading PDF: {item['title']} from {item['url']}...")
            req = urllib.request.Request(item["url"], headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(pdf_path, "wb") as f:
                    f.write(resp.read())
            print(f"Saved PDF to {pdf_path}")
        else:
            print(f"Using cached PDF file: {pdf_path}")

        reader = pypdf.PdfReader(pdf_path)
        total_pages = min(len(reader.pages), item.get("max_pages", 5))
        for page_idx in range(total_pages):
            page_text = reader.pages[page_idx].extract_text() or ""
            page_chunks = chunk_text(page_text, chunk_size=300, overlap=50)
            for c_idx, c in enumerate(page_chunks):
                chunk = {
                    "doc_id": f"{item['id']}_p{page_idx + 1}_{c_idx + 1}",
                    "source_type": "pdf",
                    "title": f"{item['title']} (Page {page_idx + 1}, Section {c_idx + 1})",
                    "content": c,
                }
                chunks.append(chunk)

    print(f"Extracted {len(chunks)} text chunks from PDF documents.")

    # 2. Download & Parse TXT
    print("\n--- 2. Downloading & Parsing In-Depth TXT Documents ---")
    for topic in TXT_WIKI_TOPICS:
        txt_path = os.path.join(txt_dir, f"{topic}.txt")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic}"
        req = urllib.request.Request(url, headers={"User-Agent": "RAG-Evaluation/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                title = data.get("title", topic)
                extract = data.get("extract", "")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(extract)

                chunk = {
                    "doc_id": f"wiki_{topic}",
                    "source_type": "txt",
                    "title": title,
                    "content": extract,
                }
                chunks.append(chunk)
                print(f"Saved TXT: {title} ({len(extract)} chars)")
        except Exception as e:
            print(f"Failed to fetch {topic}: {e}")

    # Save compiled corpus
    corpus_path = os.path.join(output_dir, "corpus.json")
    with open(corpus_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2)

    print(f"\n[OK] Complex dataset ready! Total knowledge chunks: {len(chunks)}")
    return chunks


if __name__ == "__main__":
    download_and_prepare_dataset()
