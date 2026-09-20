import os
from ico_cache.loaders.code_loader import CodeLoader

def run_code_ingestion():
    loader = CodeLoader(language="python")
    code_path = os.path.join(os.path.dirname(__file__), "data/sample_code.py")
    chunks = loader.load(code_path)

    print(f"Loaded {len(chunks)} AST chunks from {code_path}:")
    for chunk in chunks:
        print(f"[{chunk.page_or_section}] (Index: {chunk.chunk_index})")
        print("Metadata:", chunk.metadata)
        print(chunk.text)
        print("-" * 40)
    return chunks

if __name__ == "__main__":
    run_code_ingestion()
