import os
import time
import json
import requests
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="ICO-Cache Enterprise Console",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_URL = os.getenv("API_HOST", "http://127.0.0.1:8000")
LANGFUSE_URL = os.getenv("LANGFUSE_URL", "http://localhost:3001")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333/dashboard")

# --- Session State Initialization ---
if "api_key" not in st.session_state:
    st.session_state.api_key = "dev-key-default"
if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = "default"
if "model" not in st.session_state:
    st.session_state.model = "ollama/qwen2.5:3b"
if "history" not in st.session_state:
    st.session_state.history = []
if "stats" not in st.session_state:
    st.session_state.stats = {
        "total_queries": 0,
        "cache_hits": 0,
        "l1_hits": 0,
        "l2_hits": 0,
        "l3_hits": 0,
        "misses": 0,
        "time_saved_s": 0.0,
        "money_saved": 0.0,
    }


def get_headers():
    return {
        "X-API-Key": st.session_state.api_key,
        "Content-Type": "application/json",
    }


def check_api_health():
    try:
        r = requests.get(f"{API_URL}/v1/health", timeout=1.5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"status": "unreachable", "backends": {"redis": "unknown", "qdrant": "unknown"}}


# --- Sidebar: Configuration & Controls ---
with st.sidebar:
    st.title("⚡ ICO-Cache")
    st.caption("Universal Multi-Tenant Semantic Cache")

    # System Health Badge
    health = check_api_health()
    h_status = health.get("status", "degraded")
    redis_h = health.get("backends", {}).get("redis", "disconnected")
    qdrant_h = health.get("backends", {}).get("qdrant", "disconnected")

    if h_status == "ok":
        st.success(f"● Connected | Redis: {redis_h} | Qdrant: {qdrant_h}")
    else:
        st.warning(f"● Backend: {h_status} | Redis: {redis_h} | Qdrant: {qdrant_h}")

    st.divider()

    # 1. API Key Selector & Input
    st.subheader("1. Authentication")
    # WARNING: The preset keys below ('dev-key-default', 'key-tenant-a', 'key-tenant-b')
    # are insecure local development/demo fixtures ONLY. NEVER use them in production.
    # Production environments must provision unique secrets via API_KEYS env var.
    preset_keys = {
        "dev-key-default (tenant: default) [DEV ONLY]": ("dev-key-default", "default"),
        "key-tenant-a (tenant: tenant_a) [DEV ONLY]": ("key-tenant-a", "tenant_a"),
        "key-tenant-b (tenant: tenant_b) [DEV ONLY]": ("key-tenant-b", "tenant_b"),
        "Custom Production Key": ("", ""),
    }
    selected_preset = st.selectbox("API Key Preset", list(preset_keys.keys()), index=0)
    st.caption("⚠️ **Dev Notice:** Presets above are local development fixtures only. Set custom keys for production.")
    if selected_preset == "Custom Production Key":
        custom_key = st.text_input("Custom API Key", value=st.session_state.api_key, type="password")
        st.session_state.api_key = custom_key
    else:
        key_val, mapped_tenant = preset_keys[selected_preset]
        st.session_state.api_key = key_val
        st.session_state.tenant_id = mapped_tenant

    st.text_input("Active Key:", value=st.session_state.api_key, disabled=True, type="password")

    # 2. Tenant Selector / Switcher
    st.subheader("2. Multi-Tenancy")
    tenant_options = ["default", "tenant_a", "tenant_b", "Custom..."]
    curr_tenant = st.session_state.tenant_id
    t_index = tenant_options.index(curr_tenant) if curr_tenant in tenant_options else 3
    chosen_tenant = st.selectbox("Active Tenant", tenant_options, index=t_index)
    if chosen_tenant == "Custom...":
        custom_t = st.text_input("Enter Tenant ID", value=st.session_state.tenant_id)
        st.session_state.tenant_id = custom_t
    else:
        st.session_state.tenant_id = chosen_tenant

    # 3. LLM Provider & Model Selector (LiteLLM)
    st.subheader("3. LLM Engine (LiteLLM)")
    model_options = [
        "ollama/qwen2.5:3b",
        "ollama/llama3.2",
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        "anthropic/claude-3-5-sonnet-20241022",
        "gemini/gemini-1.5-flash",
        "groq/llama-3.1-70b-versatile",
        "Custom Model Spec...",
    ]
    curr_model = st.session_state.model
    m_index = model_options.index(curr_model) if curr_model in model_options else 7
    chosen_model = st.selectbox("Model Provider", model_options, index=m_index)
    if chosen_model == "Custom Model Spec...":
        custom_m = st.text_input("LiteLLM Model Name", value=st.session_state.model)
        st.session_state.model = custom_m
    else:
        st.session_state.model = chosen_model

    st.divider()

    # 7. Invalidation Controls (with confirmation)
    st.subheader("Cache Invalidation")
    with st.expander("Purge / Invalidate Cache", expanded=False):
        inval_tenant = st.text_input("Target Tenant ID", value=st.session_state.tenant_id)
        inval_filter_key = st.text_input("Filter Key (Optional)", placeholder="e.g. entity")
        inval_filter_val = st.text_input("Filter Value (Optional)", placeholder="e.g. AAPL")

        confirm_inval = st.checkbox("Confirm cache invalidation", value=False)
        if st.button("Purge Matching Entries", type="primary", disabled=not confirm_inval):
            try:
                payload = {"tenant_id": inval_tenant}
                if inval_filter_key and inval_filter_val:
                    payload["filter"] = {inval_filter_key: inval_filter_val}
                inv_res = requests.post(
                    f"{API_URL}/v1/invalidate",
                    json=payload,
                    headers=get_headers(),
                    timeout=5,
                ).json()
                st.success(
                    f"Invalidated! L1: {inv_res.get('l1_purged')}, L2: {inv_res.get('l2_purged')}, L3: {inv_res.get('l3_purged')}"
                )
                if inv_res.get("stream_event_id"):
                    st.caption(f"Redis Stream Event: `{inv_res.get('stream_event_id')}`")
            except Exception as e:
                st.error(f"Invalidation failed: {e}")

    # 8. Observability Links
    st.subheader("Observability")
    st.markdown(
        f"""
    - [🔭 Langfuse Tracing Dashboard]({LANGFUSE_URL})
    - [🗄️ Qdrant Vector Console]({QDRANT_URL})
    """
    )


# --- Main Dashboard Header & Metrics ---
st.title("⚡ Enterprise RAG Semantic Cache Console")
st.caption(
    f"Active Tenant: `{st.session_state.tenant_id}` | Active Model: `{st.session_state.model}` | Target Backend: `{API_URL}`"
)

stats = st.session_state.stats
tot = stats["total_queries"]
hit_rate = (stats["cache_hits"] / tot * 100) if tot > 0 else 0.0

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Queries", tot)
col2.metric("Overall Hit Rate", f"{hit_rate:.1f}%")
col3.metric("L1 / L2 / L3 Hits", f"{stats['l1_hits']} / {stats['l2_hits']} / {stats['l3_hits']}")
col4.metric("Latency Saved", f"{stats['time_saved_s']:.2f}s")
col5.metric("Est. Cost Saved", f"${stats['money_saved']:.3f}")

st.divider()

# --- Tabs for Query, Async Ingestion, and Auditing ---
tab_query, tab_ingest, tab_audit = st.tabs(["💬 Query & Cache Resolve", "📥 Universal Ingest", "📊 Cache Audit Log"])

# ==============================================================================
# TAB 1: Query & Cache Resolve
# ==============================================================================
with tab_query:
    st.subheader("Submit Query")

    with st.form("query_form"):
        col_q, col_c = st.columns([3, 2])
        with col_q:
            query_text = st.text_input(
                "Question:",
                value="",
                placeholder="e.g. What were Apple's major risk factors in Q4?",
            )
        with col_c:
            context_text = st.text_input(
                "Context (Optional - for L3 Cache):",
                value="",
                placeholder="e.g. Target Entity: AAPL, FY2024",
            )

        submit_btn = st.form_submit_button("Resolve Query", type="primary", use_container_width=True)

    if submit_btn and query_text:
        with st.spinner("Resolving across L1, L2, L3 cache layers..."):
            try:
                t_start = time.time()
                payload = {
                    "query": query_text,
                    "context": context_text if context_text else None,
                    "tenant_id": st.session_state.tenant_id,
                    "model": st.session_state.model,
                }
                res = requests.post(
                    f"{API_URL}/v1/compare",
                    json=payload,
                    headers=get_headers(),
                    timeout=30,
                ).json()

                cached_part = res.get("cached", {})
                fresh_part = res.get("fresh", {})

                cached_resp = cached_part.get("response", {})
                source = cached_resp.get("source", "MISS")
                cached_data = cached_resp.get("response") or {}

                # Determine Answer
                if isinstance(cached_data, dict):
                    answer = cached_data.get("answer", "") or cached_data.get("content", "")
                    citations = cached_data.get("citations", [])
                    metadata_fields = cached_data.get("metadata", {})
                    loader_used = cached_data.get("loader_type", "TextLoader")
                    extraction_method = cached_data.get("extraction_method", "direct")
                else:
                    answer = str(cached_data)
                    citations = []
                    metadata_fields = {}
                    loader_used = "TextLoader"
                    extraction_method = "direct"

                t_cached = cached_part.get("latency_s", 0.0)
                t_fresh = fresh_part.get("latency_s", 0.0)

                # Update Stats
                stats["total_queries"] += 1
                is_hit = source in ["L1", "L2", "L3"]
                if is_hit:
                    stats["cache_hits"] += 1
                    if source == "L1":
                        stats["l1_hits"] += 1
                    elif source == "L2":
                        stats["l2_hits"] += 1
                    elif source == "L3":
                        stats["l3_hits"] += 1
                    stats["time_saved_s"] += max(0.0, t_fresh - t_cached)
                    stats["money_saved"] += 0.015  # estimated cost per LLM call
                else:
                    stats["misses"] += 1

                # 6. Cache Layer Indicator
                st.markdown("### Resolution Result")
                col_badge, col_lat, col_sav = st.columns([2, 1, 1])
                with col_badge:
                    if source == "L1":
                        st.success("🟢 **L1 HIT** — Exact Key Cache (Instant In-Memory/Redis)")
                    elif source == "L2":
                        st.info("🔵 **L2 HIT** — Semantic Vector Cache (Qdrant Cosine Similarity)")
                    elif source == "L3":
                        st.info("🟣 **L3 HIT** — Context-Aware Cache (Dual-Vector Match)")
                    else:
                        st.warning("🐢 **CACHE MISS** — RAG Fallback (Generated via LLM)")

                with col_lat:
                    st.metric("Actual Latency", f"{t_cached*1000:.1f} ms")
                with col_sav:
                    speedup = (t_fresh / t_cached) if t_cached > 0 else 1.0
                    st.metric("Without Cache", f"{t_fresh*1000:.1f} ms", delta=f"{speedup:.1f}x faster")

                # Display Response Answer
                st.markdown("#### Generated / Cached Response")
                st.write(answer if answer else "No response text available.")

                # 5. Per-Chunk Metadata Display
                if citations or metadata_fields:
                    with st.expander("🔍 Per-Chunk Metadata & Source Verification", expanded=True):
                        col_m1, col_m2, col_m3 = st.columns(3)
                        col_m1.markdown(f"**Loader Type:** `{loader_used}`")
                        col_m2.markdown(f"**Extraction Method:** `{extraction_method}`")
                        col_m3.markdown(f"**Metadata Schema Fields:** `{len(metadata_fields)} field(s)`")

                        if metadata_fields:
                            st.json(metadata_fields)

                        if citations:
                            st.markdown("**Citations & Chunk Sources:**")
                            for idx, cit in enumerate(citations):
                                if isinstance(cit, dict):
                                    st.markdown(
                                        f"- **Chunk {idx+1}:** `{cit.get('source', '')}` (Section: `{cit.get('section', 'N/A')}`, Loader: `{cit.get('loader_type', 'N/A')}`, Extractor: `{cit.get('extraction_method', 'N/A')}`)"
                                    )
                                    if cit.get("content"):
                                        st.caption(f"> {cit.get('content')[:200]}...")
                                else:
                                    st.markdown(f"- **Chunk {idx+1}:** `{cit}`")

                # Record in Audit History
                st.session_state.history.append({
                    "Timestamp": time.strftime("%H:%M:%S"),
                    "Tenant": st.session_state.tenant_id,
                    "Query": query_text,
                    "Context": context_text,
                    "Source": source,
                    "Status": "✅ HIT" if is_hit else "🐢 MISS",
                    "Latency (Actual)": f"{t_cached*1000:.1f} ms",
                    "Latency (Without Cache)": f"{t_fresh*1000:.1f} ms",
                    "Model": st.session_state.model,
                })

            except Exception as e:
                st.error(f"Failed to query API: {e}")

# ==============================================================================
# TAB 2: Universal Async Ingestion Flow
# ==============================================================================
with tab_ingest:
    st.subheader("Universal Multi-Format Document Ingestion")
    st.markdown(
        "Upload files or select corpus files to ingest into the active tenant. "
        "Files are processed with `AutoLoader` (PDF with OCR fallback, CSV coalescing, Code, Markdown) "
        "and written to Redis & Qdrant asynchronously."
    )

    ingest_col1, ingest_col2 = st.columns([1, 1])

    with ingest_col1:
        st.markdown("#### Option A: Upload a Document")
        uploaded_file = st.file_uploader(
            "Upload file",
            type=["txt", "pdf", "csv", "json", "jsonl", "py", "js", "go", "html"],
            key="file_uploader",
        )
        force_async = st.checkbox("Force Asynchronous Background Worker", value=True)

        if st.button("Ingest Uploaded File", type="primary", disabled=uploaded_file is None):
            with st.spinner("Submitting document to ingestion worker..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                    data = {
                        "tenant_id": st.session_state.tenant_id,
                        "force_async": str(force_async).lower(),
                    }
                    upload_headers = {"X-API-Key": st.session_state.api_key}
                    resp = requests.post(
                        f"{API_URL}/v1/ingest/upload",
                        files=files,
                        data=data,
                        headers=upload_headers,
                        timeout=15,
                    ).json()

                    job_id = resp.get("job_id")
                    st.info(f"Ingestion job queued: `{job_id}` (async={resp.get('is_async')})")

                    # 4. Async Ingestion Flow with Live Polling
                    if job_id and resp.get("is_async"):
                        progress_bar = st.progress(0.0)
                        status_container = st.status(f"Processing ingestion job {job_id}...", expanded=True)

                        done = False
                        poll_attempts = 0
                        while not done and poll_attempts < 60:
                            time.sleep(0.5)
                            poll_attempts += 1
                            job_data = requests.get(
                                f"{API_URL}/v1/ingest/jobs/{job_id}",
                                headers=get_headers(),
                                timeout=5,
                            ).json()

                            status = job_data.get("status", "processing")
                            tot_c = max(1, job_data.get("chunks_total", 1))
                            proc_c = job_data.get("chunks_processed", 0)
                            progress_ratio = min(1.0, proc_c / tot_c)
                            progress_bar.progress(progress_ratio)

                            status_container.write(
                                f"Status: `{status}` | Chunks Processed: `{proc_c} / {tot_c}` | Elapsed: `{job_data.get('elapsed_s', 0):.1f}s`"
                            )

                            if status in ["completed", "failed"]:
                                done = True
                                if status == "completed":
                                    status_container.update(
                                        label=f"✓ Ingestion Completed! Ingested {proc_c} chunks in {job_data.get('elapsed_s', 0):.2f}s",
                                        state="complete",
                                    )
                                    st.success(f"Successfully ingested `{uploaded_file.name}` into `{st.session_state.tenant_id}`!")
                                else:
                                    status_container.update(
                                        label=f"✕ Ingestion Failed: {job_data.get('error')}",
                                        state="error",
                                    )
                                    st.error(f"Error: {job_data.get('error')}")

                except Exception as e:
                    st.error(f"Upload and ingestion error: {e}")

    with ingest_col2:
        st.markdown("#### Option B: Ingest from Test Corpus")
        sample_corpus_files = [
            "examples/test-corpus/text/standard.txt",
            "examples/test-corpus/text/clean.pdf",
            "examples/test-corpus/text/scanned.pdf",
            "examples/test-corpus/structured/standard.csv",
            "examples/test-corpus/structured/standard.jsonl",
            "examples/test-corpus/code/standard.py",
            "examples/test-corpus/code/standard.js",
            "examples/test-corpus/code/standard.go",
        ]
        chosen_corpus_file = st.selectbox("Select Test Corpus File", sample_corpus_files)

        if st.button("Ingest Corpus File", type="secondary"):
            with st.spinner("Submitting corpus file..."):
                try:
                    payload = {
                        "file_path": chosen_corpus_file,
                        "tenant_id": st.session_state.tenant_id,
                        "force_async": True,
                    }
                    resp = requests.post(
                        f"{API_URL}/v1/ingest",
                        json=payload,
                        headers=get_headers(),
                        timeout=10,
                    ).json()

                    job_id = resp.get("job_id")
                    st.info(f"Ingestion job dispatched: `{job_id}`")

                    # Live Polling
                    progress_bar = st.progress(0.0)
                    status_container = st.status(f"Processing corpus job {job_id}...", expanded=True)

                    done = False
                    poll_attempts = 0
                    while not done and poll_attempts < 60:
                        time.sleep(0.5)
                        poll_attempts += 1
                        job_data = requests.get(
                            f"{API_URL}/v1/ingest/jobs/{job_id}",
                            headers=get_headers(),
                            timeout=5,
                        ).json()

                        status = job_data.get("status", "processing")
                        tot_c = max(1, job_data.get("chunks_total", 1))
                        proc_c = job_data.get("chunks_processed", 0)
                        progress_ratio = min(1.0, proc_c / tot_c)
                        progress_bar.progress(progress_ratio)

                        status_container.write(
                            f"Status: `{status}` | Chunks Processed: `{proc_c} / {tot_c}` | Elapsed: `{job_data.get('elapsed_s', 0):.1f}s`"
                        )

                        if status in ["completed", "failed"]:
                            done = True
                            if status == "completed":
                                status_container.update(
                                    label=f"✓ Completed! {proc_c} chunks in {job_data.get('elapsed_s', 0):.2f}s",
                                    state="complete",
                                )
                                st.success(f"Ingested `{chosen_corpus_file}` into tenant `{st.session_state.tenant_id}`.")
                            else:
                                status_container.update(
                                    label=f"✕ Failed: {job_data.get('error')}",
                                    state="error",
                                )
                                st.error(f"Error: {job_data.get('error')}")

                except Exception as e:
                    st.error(f"Corpus ingestion error: {e}")

# ==============================================================================
# TAB 3: Audit Log & Cache Layer Dashboard
# ==============================================================================
with tab_audit:
    st.subheader("Query Audit Log & Layer Breakdown")

    if st.session_state.history:
        df = pd.DataFrame(st.session_state.history)
        st.dataframe(df, use_container_width=True, hide_index=True)

        col_clr1, col_clr2 = st.columns([1, 4])
        with col_clr1:
            if st.button("Clear Log Table"):
                st.session_state.history = []
                st.rerun()
        with col_clr2:
            if st.button("Reset Entire Cache & History", type="primary"):
                try:
                    requests.post(f"{API_URL}/v1/clear_cache", headers=get_headers(), timeout=5)
                    st.session_state.history = []
                    st.session_state.stats = {
                        "total_queries": 0,
                        "cache_hits": 0,
                        "l1_hits": 0,
                        "l2_hits": 0,
                        "l3_hits": 0,
                        "misses": 0,
                        "time_saved_s": 0.0,
                        "money_saved": 0.0,
                    }
                    st.success("Cache cleared across active tenant.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to clear cache: {e}")
    else:
        st.info("No queries recorded yet in this session. Submit questions from the Query tab to see real-time cache analytics.")
