import os
from ico_cache.loaders.structured_loader import StructuredLoader

def run_structured_ingestion():
    loader = StructuredLoader()
    csv_path = os.path.join(os.path.dirname(__file__), "data/products.csv")
    chunks = loader.load(csv_path)

    print(f"Loaded {len(chunks)} structured chunks from {csv_path}:")
    for chunk in chunks:
        print(f"[{chunk.page_or_section}] (Index: {chunk.chunk_index})")
        print(chunk.text)
        print("Metadata:", chunk.metadata)
        print("-" * 40)
    return chunks

if __name__ == "__main__":
    run_structured_ingestion()
