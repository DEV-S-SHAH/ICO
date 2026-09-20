# PRODUCTION CHECKLIST

## PHASE 1 — DATASET
- [x] datasets/ingestion/sec_edgar_fetcher.py
- [x] datasets/ingestion/sec_cleaner.py
- [x] datasets/ingestion/chunker.py
- [x] Query sets built
- [x] datasets/README.md

## PHASE 2 — INFRASTRUCTURE
- [x] docker-compose.yml
- [x] Services reachable (Qdrant, Redis, Langfuse)
- [x] Ingest Phase 1 chunks into Qdrant

## PHASE 3 — CACHE LOGIC
- [x] L1 EXACT
- [x] L2 SEMANTIC
- [x] L3 CONTEXT
- [x] MISS (LangGraph pipeline)
- [x] Langfuse tracing
- [x] Concurrency test

## PHASE 4 — API + FASTAPI
- [x] /query endpoint
- [x] /compare endpoint
- [x] /eval endpoint
- [x] /stats endpoint

## PHASE 5 — EVAL
- [x] Run 500 queries
- [x] False-hit count on near_miss_negatives is 0
- [x] Threshold calibration evidence

## PHASE 6 — STREAMLIT UI
- [x] Query console
- [x] Per-layer test tabs
- [x] Compare view
- [x] Metrics dashboard
- [x] Embedded Qdrant/Langfuse
- [x] Session_state duplicate prevention
