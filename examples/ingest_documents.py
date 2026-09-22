import os
from ico_cache.loaders.txt_loader import TXTLoader

def run_document_ingestion():
    loader = TXTLoader()
    doc_path = os.path.join(os.path.dirname(__file__), "data/sample.txt")
    chunks = loader.load(doc_path)

    print(f"Loaded {len(chunks)} text chunks from {doc_path}:")
    for chunk in chunks:
        print(f"[{chunk.page_or_section}] (Index: {chunk.chunk_index})")
        print(chunk.text)
        print("-" * 40)
    return chunks

if __name__ == "__main__":
    run_document_ingestion()
