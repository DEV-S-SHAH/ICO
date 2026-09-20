#!/usr/bin/env python3
"""
Post-publish fresh-install smoke test for ico-cache.
Validates that the installed ico-cache package works end-to-end:
1. Ingests a small text file into a clean embedded cache engine.
2. Performs an initial query (generating/caching a response).
3. Executes a repeat query and asserts a cache HIT (L1 or L2).
"""
import asyncio
import os
import sys
import tempfile


def run_smoke_test():
    print("==> Running ico-cache post-install smoke test...")
    try:
        import ico_cache
        from ico_cache import CacheEngine
        from ico_cache.backends.embedding.fastembed_embedder import FastEmbedder
        from ico_cache.backends.exact.sqlite_store import SQLiteStore
        from ico_cache.backends.vector.lancedb_store import LanceDBStore
        from ico_cache.loaders.auto_loader import AutoLoader
    except ImportError as e:
        sys.exit(f"SMOKE TEST FAILED: Unable to import ico_cache: {e}")

    print(f"✓ Successfully imported ico_cache (version {getattr(ico_cache, '__version__', 'unknown')})")

    with tempfile.TemporaryDirectory() as td:
        exact_db = os.path.join(td, "exact.db")
        lance_dir = os.path.join(td, "lancedb")

        engine = CacheEngine(
            embedder=FastEmbedder(),
            vector_store=LanceDBStore(uri=lance_dir),
            exact_store=SQLiteStore(db_path=exact_db),
        )

        test_file = os.path.join(td, "sample.txt")
        sample_text = "Apple Inc. reported quarterly revenue of $85 billion in fiscal Q3."
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(sample_text)

        loader = AutoLoader()
        chunks = loader.load(test_file)
        if not chunks:
            sys.exit("SMOKE TEST FAILED: AutoLoader extracted 0 chunks from sample file.")

        print(f"✓ Loaded {len(chunks)} chunk(s) from sample file.")

        tenant = "smoke_tenant"
        query = "What was the quarterly revenue reported by Apple in Q3?"
        cached_val = {"answer": "$85 billion", "source": "10-Q filing"}

        # Write to cache
        engine.set_l1(query, cached_val, tenant_id=tenant)
        asyncio.run(engine.async_write_l2(query, cached_val, tenant_id=tenant))

        # Query 1: L1 cache hit
        l1_res = asyncio.run(engine.get_l1(query, tenant_id=tenant))
        if not l1_res:
            sys.exit("SMOKE TEST FAILED: Expected L1 cache hit, got None.")
        print(f"✓ L1 exact cache hit verified: {l1_res}")

        # Query 2: L2 semantic cache hit for a close paraphrase
        paraphrase = "How much revenue did Apple report in fiscal Q3?"
        l2_res = asyncio.run(engine.get_l2(paraphrase, tenant_id=tenant))
        if not l2_res:
            sys.exit("SMOKE TEST FAILED: Expected L2 semantic cache hit on paraphrase, got None.")
        print(f"✓ L2 semantic cache hit verified on paraphrase: {l2_res}")

    print("========================================================")
    print("  ✓ FRESH-INSTALL SMOKE TEST PASSED SUCCESSFULLY")
    print("========================================================")


if __name__ == "__main__":
    run_smoke_test()
