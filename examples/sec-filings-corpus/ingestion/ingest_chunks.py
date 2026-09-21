import json
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding

CHUNKS_FILE = Path("data/chunks/all_chunks.jsonl")
COLLECTION_NAME = "ico_corpus"

def main():
    print("Loading chunks...")
    chunks = []
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            chunks.append(json.loads(line))
            
    print(f"Loaded {len(chunks)} chunks.")
    
    print("Initializing embedding model...")
    # Using a fast embedding model
    embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    
    texts = [c["text"] for c in chunks]
    print("Computing embeddings... (this may take a minute)")
    # fastembed returns a generator
    embeddings = list(embedding_model.embed(texts))
    
    print("Connecting to Qdrant...")
    client = QdrantClient("localhost", port=6333)
    
    # Create or recreate collection
    if client.collection_exists(collection_name=COLLECTION_NAME):
        client.delete_collection(collection_name=COLLECTION_NAME)
        
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )
    
    print("Inserting points...")
    points = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        points.append(
            PointStruct(
                id=i,
                vector=emb.tolist(),
                payload={
                    "text": chunk["text"],
                    **chunk["metadata"]
                }
            )
        )
        
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=points
    )
    
    print(f"Inserted {len(points)} points into Qdrant collection '{COLLECTION_NAME}'.")

if __name__ == "__main__":
    main()
