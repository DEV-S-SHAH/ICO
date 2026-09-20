import json
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, SparseVectorParams
from fastembed import TextEmbedding, SparseTextEmbedding

CHUNKS_FILE = Path("datasets/chunks/all_chunks.jsonl")
COLLECTION_NAME = "ico_corpus"

def main():
    print("Loading chunks...")
    chunks = []
    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            chunks.append(json.loads(line))
            
    print(f"Loaded {len(chunks)} chunks.")
    
    print("Initializing embedding models...")
    dense_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    
    texts = [c["text"] for c in chunks]
    print("Computing dense embeddings...")
    dense_embeddings = list(dense_model.embed(texts))
    
    print("Computing sparse embeddings...")
    sparse_embeddings = list(sparse_model.embed(texts))
    
    print("Connecting to Qdrant...")
    client = QdrantClient("localhost", port=6333)
    
    if client.collection_exists(collection_name=COLLECTION_NAME):
        client.delete_collection(collection_name=COLLECTION_NAME)
        
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "text-dense": VectorParams(size=384, distance=Distance.COSINE)
        },
        sparse_vectors_config={
            "text-sparse": SparseVectorParams()
        }
    )
    
    print("Inserting points...")
    points = []
    for i, (chunk, d_emb, s_emb) in enumerate(zip(chunks, dense_embeddings, sparse_embeddings)):
        # s_emb has .indices and .values
        sparse_vector = {"indices": s_emb.indices.tolist(), "values": s_emb.values.tolist()}
        
        points.append(
            PointStruct(
                id=i,
                vector={
                    "text-dense": d_emb.tolist(),
                    "text-sparse": sparse_vector
                },
                payload={
                    "text": chunk["text"],
                    **chunk["metadata"]
                }
            )
        )
        
    # batch upload
    for batch_idx in range(0, len(points), 100):
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points[batch_idx:batch_idx+100]
        )
    
    print(f"Inserted {len(points)} points with hybrid vectors into '{COLLECTION_NAME}'.")

if __name__ == "__main__":
    main()
