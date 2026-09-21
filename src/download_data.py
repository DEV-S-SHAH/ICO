"""Multi-format Dataset Downloader & Parser powered by PyPI's ico-cache AutoLoader."""

import io
import json
import logging
import os
import urllib.request
from typing import Dict, List

try:
    from ico_cache import AutoLoader
    HAS_ICO_CACHE = True
except ImportError:
    HAS_ICO_CACHE = False
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


def download_and_prepare_dataset(output_dir: str = "data/complex_dataset") -> List[Dict[str, str]]:
    """Download PDF research papers and TXT articles, parse chunks, and compile corpus."""
    os.makedirs(output_dir, exist_ok=True)
    pdf_dir = os.path.join(output_dir, "pdfs")
    txt_dir = os.path.join(output_dir, "txts")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(txt_dir, exist_ok=True)

    chunks = []

    # 1. Download & Parse PDF using ico-cache AutoLoader
    print("\n--- 1. Downloading & Parsing Complex PDF Documents (via ico-cache) ---")
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

        if HAS_ICO_CACHE:
            auto_loader = AutoLoader()
            parsed_chunks = auto_loader.load(pdf_path)
            for idx, c in enumerate(parsed_chunks[:item.get("max_pages", 5)]):
                chunk = {
                    "doc_id": f"{item['id']}_p{idx + 1}",
                    "source_type": "pdf",
                    "title": f"{item['title']} (Page {idx + 1})",
                    "content": c.text.strip(),
                }
                chunks.append(chunk)
        else:
            import pypdf
            reader = pypdf.PdfReader(pdf_path)
            for idx in range(min(len(reader.pages), item.get("max_pages", 5))):
                chunk = {
                    "doc_id": f"{item['id']}_p{idx + 1}",
                    "source_type": "pdf",
                    "title": f"{item['title']} (Page {idx + 1})",
                    "content": reader.pages[idx].extract_text() or "",
                }
                chunks.append(chunk)

    print(f"Extracted {len(chunks)} text chunks from PDF documents.")

    # 2. Download & Parse TXT using ico-cache AutoLoader
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

                if HAS_ICO_CACHE:
                    auto_loader = AutoLoader()
                    txt_chunks = auto_loader.load(txt_path)
                    content = txt_chunks[0].text if txt_chunks else extract
                else:
                    content = extract

                chunk = {
                    "doc_id": f"wiki_{topic}",
                    "source_type": "txt",
                    "title": title,
                    "content": content,
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
