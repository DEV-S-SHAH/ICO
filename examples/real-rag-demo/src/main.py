"""Main runner for Real RAG Demo."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
import uvicorn

_SRC_DIR = Path(__file__).resolve().parent
_DEMO_DIR = _SRC_DIR.parent
_REPO_ROOT = _DEMO_DIR.parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))
if str(_REPO_ROOT / "packages" / "ico-cache-py" / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "packages" / "ico-cache-py" / "src"))

try:
    from .config import config
    from .api import create_demo_app
except ImportError:
    from src.config import config
    from src.api import create_demo_app


def main():
    parser = argparse.ArgumentParser(description="ICO-Cache Real RAG Demo")
    parser.add_argument("--host", type=str, default=config.api_host, help="Host to bind server")
    parser.add_argument("--port", type=int, default=config.api_port, help="Port to bind server")
    parser.add_argument("--reload", action="store_true", help="Enable reload")
    parser.add_argument("--ingest", action="store_true", help="Run document ingestion only and exit")
    parser.add_argument("--query", type=str, default=None, help="Run single query via CLI and print output")

    args = parser.parse_args()

    app = create_demo_app(config)

    if args.ingest:
        print("[INGEST] Starting document ingestion...")
        ingestion = app.state.ingestion
        chunks, corpus_v = ingestion.extract_chunks()
        print(f"[INGEST] Ingested {len(chunks)} chunks from {config.documents_dir}")
        print(f"[INGEST] Corpus Version: {corpus_v}")
        return

    if args.query:
        async def run_cli_query():
            # Trigger startup ingestion
            chunks, corpus_v = app.state.ingestion.extract_chunks()
            app.state.corpus_version = corpus_v
            app.state.chunks = chunks
            if chunks:
                vectors = app.state.embedder.embed_batch([c["text"] for c in chunks])
                await app.state.vector_store.insert_chunks(chunks, vectors)

            from httpx import AsyncClient, ASGITransport
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/rag/query", json={"query": args.query})
                data = resp.json()
                print("\n" + "="*60)
                print(f"QUERY: {args.query}")
                print(f"ANSWER:\n{data['answer']}")
                print("\nSOURCES:")
                for s in data["sources"]:
                    print(f" - {s['document']} (Page {s['page']}, Chunk: {s['chunk_id']})")
                print(f"\nCACHE: hit={data['cache']['hit']}, layer={data['cache']['layer']}")
                print(f"LATENCY: {data['latency_ms']}ms | REQUEST ID: {data['request_id']}")
                print("="*60 + "\n")

        asyncio.run(run_cli_query())
        return

    print(f"Starting ICO-Cache Real RAG API on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
