# Graph RAG Financial Intelligence Terminal — Build Prompt

> Paste this prompt verbatim into your AI engineering agent (opencode / Claude Code / Cursor).
> It targets this repository (`ICO`) and builds the product on top of the existing,
> already-hardened `ico-cache` library. Follow ALL rules below — do not skip steps.

---

## Mission

Build **Graph-RAG Financial Intelligence** ("the Terminal"): a production-grade product that
ingests several years of a company's **stock data (yfinance)**, **news**, **SEC filings** and
**official reports** (HTML/PDF), builds a financial **knowledge graph**, and surfaces
**risk / investment / custom analytics** through a minimal, dense **Bloomberg-terminal-style**
frontend. The `ico-cache` engine shipped in this repo must be hardened to **production level
and packaged/installable by anyone** (`pip install` / `pip install -e`), while staying fully
backward compatible with its existing tests.

Your follow-up objective: turn ico-cache into a drop-in dependency (PyPI `ico-cache` +
npm `ico-cache-js`) that other projects can `import` and deploy via the Helm chart.

---

## Step 0 — Analyze the repo first (MANDATORY, do not skip)

Before writing any code, run GitNexus graph intelligence on the working tree: `analyze --index-only` if stale.

1. `node .gitnexus/run.cjs status --repo .` — check index freshness; if stale run
   `node .gitnexus/run.cjs analyze --index-only --repo .`.
2. `node .gitnexus/run.cjs query "semantic cache resolve generate" --repo .`
3. `node .gitnexus/run.cjs query "universal document ingestion" --repo .`
4. `node .gitnexus/run.cjs impact "CacheEngine.resolve_or_generate" --direction upstream --repo .`
5. Read for yourself: `packages/ico-cache-py/src/ico_cache/core/cache_engine.py`,
   `packages/ico-cache-py/src/ico_cache/loaders/auto_loader.py`,
   `packages/ico-cache-py/src/ico_cache/rag/pipeline.py`,
   `apps/financial-rag-demo/api/main.py`, `packages/ico-cache-py/pyproject.toml`,
   `docs/ARCHITECTURE.md`.

**Working rules that apply for the whole task:**
- Run `impact` on a symbol BEFORE you edit it; never edit a function/class without knowing callers and risk. Treat `risk: UNKNOWN` as unresolved — confirm with text search before deleting anything.
- Run `detect-changes --scope all --repo .` before every commit; a truncated/partial result is NOT clean — re-run until complete.
- Do not weaken assertions. The suite is dataset-free by contract: all fixtures are generated at runtime (`packages/ico-cache-py/tests/fixtures_gen.py`). Never re-add data files.
- Never commit secrets. Use `.env` (gitignored) for real keys; `REPLACE_WITH_*` placeholders in committed files.
- Follow existing code style (ruff/mypy config at repo root). Reuse existing components; do not fork behaviour into a second copy.

---

## Step 1 — Reuse & package ico-cache as an installable dependency

1. **Package surface.** Verify `packages/ico-cache-py` ships a clean `import` surface and extras:
   - `pip install -e "packages/ico-cache-py[loaders,observability]"`
   - `ico_cache` exports: `CacheEngine`, `IngestionJobManager`, `AutoLoader`, `ingest`, `configure_ocr`, telemetry helpers.
   - Keep `README` badges accurate (Python 3.11+, no bundled datasets).
2. **Reproducible build.** (`python -m build` → `twine check` clean, wheel contains only `ico_cache*`).
3. **Publish path** (documented, not necessarily executed): TestPyPI first, then PyPI. Version scheme stays semver; pre-release = `1.1.0rc1`.
4. **JS SDK** `packages/ico-cache-js`: type-safe client for every `/v1/*` route (query, ingest, ingest/jobs, invalidate, health, ready, metrics), Node >=20, released to npm as `ico-cache-js`.
5. **Deployability:** `deploy/helm/ico-cache` remains the reference install; add a `docs/DEPLOYMENT.md` walkthrough (helm → kubectl → smoke via `/v1/ready`).

**Done when:** `pip install .` in a fresh venv works, `from ico_cache import CacheEngine` succeeds, wheel is clean, JS build passes on Node 20, helm `lint`+`template` pass.

---

## Step 2 — Financial knowledge graph on top of ico-cache

Add a new package (e.g. `apps/graph-rag/` or `packages/ico-finance/` — your call, keep it importable,
pip-installable, and covered by tests in the existing dataset-free style).

### Data connectors (runbook-driven, no data committed)
- **yfinance**: OHLCV + fundamentals (income/balance/cash-flow), daily history for N years (N>=3).
- **News**: RSS/API articles; normalize by ticker.
- **SEC filings**: reuse `examples/sec-filings-corpus/ingestion/*.py` (fetcher, cleaner, chunker) to pull 10-K/10-Q/8-K per ticker for several years.
- **Official reports**: PDF/HTML from IR sites — ingest through `AutoLoader` (content-sniffing + OCR).
- Persist raw + normalized parquet/knowledge-layer in a `./data/` dir (gitignored) or object storage; never commit.

### Graph model (recommended schema — extend as needed)
- **Nodes**: `Company(ticker)`, `Executive`, `BoardMember`, `Division`, `Product/Service`, `Metric(financial statement line)`, `Report(10-K/10-Q/8-K, source URL)`, `NewsArticle`, `Covenant/CreditFacility`, `RiskFactor`, `Segment`, `Event(dates, type)`.
- **Edges**: `reports_to`, `signs (report)`, `mentions (metric)`, `drives (revenue)`, `exposes_to (risk)`, `occurs_on (event date)`, `affects (stock price)`, `issued (bonds)`, `refis → refinancing` etc. Include a `confidence` and a citation `source` + `provenance` (`source_file`, page) on every relationship — ico-cache metadata contracts must be honored (JSON-encodable payloads, filter keys).
- Store graph edges/schema in **Qdrant (vector) + Redis (exact)** for tenants, embedding text like
  `"CEO X of <ticker> signed 10-K dated Y; risk Z mentioned on page P"` with the existing `CacheEngine` embedding path. Keep the triple payloads on the vector points.
- **Universe bootstrap**: `python -m ico_finance.build --tickers AAPL,MSFT,JPM --years 3` fetches data, builds the graph, and runs a validation report (node/edge counts, dangling refs, citability).

### Query layer ("insights")
Build a reasoning module over the graph (verbose `litellm` calls, provider-agnostic) that answers, with citations:
- **Risk analysis**: risk-factor trend across years, new/exiting risks, covenant/refinancing risk, segment concentration, FX/rates exposure, litigation events.
- **Investment thesis**: Bull/Bear/Base with supporting evidence edges, valuation comps (PS/PE/EV-EBITDA), dividend/buyback policy, insider activity.
- **Quant analytics**: yfinance-derived indicators (SMA/RSI/MACD, momentum, vol, drawdown), fundamental deltas (revenue growth, margin trend, FCF conversion), factor scores.
- **Custom**: ad-hoc NL questions over your schema.
- Every claim must be traced back to a node/edge with `source_file` + page/paragraph via the gated metadata system (this is exactly what `hard_gate` + L3 dual-context enable). Output structured JSON (`{answer, citations: [{source, page, quote}], confidence, graph_subgraph}`).

---

## Step 3 — The Terminal UI (minimal Bloomberg terminal)

A client-side-first web app (or Streamlit deep-dive + a fast React/TypeScript shell — your call, but it must look professional and dense). Dark theme, high information density, keyboard-first navigation.

- **Top command bar**: ticker + exchange + watchlist, command line style input (startup keyboard focus), company descriptor line (e.g. `AAPL — AAPL US — Technology: Computers`).
- **Multi-pane monitor grid** (re-flowable):
  1. **Chart pane**: candle/OHLCV with volume, SMA/RSI/MACD overlays, multi-year range buttons, annotations from events (`earnings`, `10-K filed`, `analyst actions`).
  2. **Risks pane**: risk trend (YoY deltas), top risk factors w/ severity, citation drill-down.
  3. **Fundamentals pane**: income/balance/cash-flow snapshot, margin & growth trendline table.
  4. **News / filings feed**: headline strip with source + recency filter.
  5. **Investment thesis pane**: Bull/Bear/Base cards, valuation comps table, target ranges.
  6. **Watchlist rail** + autosuggest, plus a query box that runs the custom reasoning endpoint.
- **Rendering:** dense tables (monospace numerals), sparklines, color = semantic (red down / green up per US convention), no janky animations, print-friendly export of a thesis report.
- Wire UI → API layer: `/v1/query` for LLM RAG, plus new health-checked endpoints: `/v1/graph/{ticker}` (subgraph JSON), `/v1/fundamentals/{ticker}`, `/v1/news/{ticker}`, `/v1/risks/{ticker}`. Keep ico-cache rate limiting, metrics, `/v1/ready` semantics intact; each new endpoint must record to Prometheus and be covered by tests.

---

## Step 4 — Production hardening of the new surface

- **Security:** per-tenant API keys, same auth middleware; never expose raw API keys; validate all inputs (ticker regex `^[A-Z.\-]{1,10}$`, strict date parsing, pagination caps).
- **Reliability:** every external fetch (yfinance, EDGAR, news) is idempotent, retried with backoff, cached with the 3-tier cache, and bounded by timeouts; ingestion jobs go through `IngestionJobManager` (async for large PDFs).
- **Observability:** metrics per pipeline stage (fetch→normalize→chunk→embed→graph→answer), traces via existing OTel/Langfuse wiring, JSON logs.
- **Cost control:** cache-before-generate everywhere; batch embeddings; rank graph retrieval before LLM; token budget + stop conditions in `rag/pipeline.py`.
- **Testing (dataset-free, synthetic):** unit tests for connectors (mocked), graph build (tiny synthetic ticker), risk/thesis reasoning (deterministic fake LLM), gating/citation correctness (0 false positives), API route tests via `TestClient`, and a concurrency test proving single-flight for the same insight query. Keep everything running offline with generated fixtures.
- **Ops:** extend helm with a `graph-worker` Deployment (cron/controller) and new API env; add PDBs, securityContexts consistent with existing ones; update CI to type-check/lint/test the new packages; keep CodeQL + Dependabot covering them.

---

## Step 5 — Docs & release

- Update `README.md` (new "Graph RAG Financial Intelligence" section, architecture diagram, quickstart that a stranger can follow in 5 minutes, screenshots of the Terminal if you implement the UI).
- `CHANGELOG.md` — new entries under `[Unreleased]`.
- `docs/GRAPH_RAG.md` — data pipeline, graph schema, insight methodology, runbook.
- Release checklist: bump version, `python -m build` + `twine check`, publish TestPyPI → PyPI, npm `ico-cache-js`, helm chart bump, GitHub Release notes referencing the changelog.

---

## Verification (must pass before you call it done)

```bash
# From the repo root
ruff check packages/ico-cache-py/src apps apps/graph-rag
mypy packages/ico-cache-py/src

PYTHONPATH=packages/ico-cache-py/src:. venv/bin/python -m pytest packages/ico-cache-py/tests/ -q
PYTHONPATH=packages/ico-cache-py/src:. venv/bin/python eval_harness.py --eval-adversarial

helm lint deploy/helm/ico-cache && helm template ico-cache deploy/helm/ico-cache >/dev/null
cd packages/ico-cache-js && npm i && npm run build

# New graph-rag package, if created:
PYTHONPATH=packages/ico-cache-py/src:. venv/bin/python -m pytest <graph-rag>/tests/ -q
```

## Definition of done

1. `pip install "ico-cache[loaders,observability]"` works for a stranger; `ico_cache` imports; JS SDK builds on Node 20.
2. `python -m ico_finance.build --tickers <T> --years 3` produces a validated, citable knowledge graph with 0 dangling references.
3. Risk / investment / custom insight endpoints return cited JSON; `hard_gate` blocks cross-ticker/quarter false hits at 0%.
4. The Terminal UI renders as a minimal Bloomberg terminal (dark, dense, keyboard-first, multi-pane) and every pane is wired to a live, health-chcked API endpoint.
5. All of the above is shipped with tests, docs, CI, and the hardened Helm chart — and pushed. Then stop; do not invent new scope.