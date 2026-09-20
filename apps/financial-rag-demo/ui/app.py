import os
import streamlit as st
import requests
import time
import pandas as pd

st.set_page_config(page_title="ICO-Agent", layout="wide")

API_URL = os.getenv("API_HOST", "http://api:8000")

# --- State Initialization ---
if 'history' not in st.session_state:
    st.session_state.history = []
if 'stats' not in st.session_state:
    st.session_state.stats = {
        'total_queries': 0,
        'cache_hits': 0,
        'time_saved_s': 0.0,
        'money_saved': 0.0,
    }

st.title("ICO-Agent: Enterprise RAG Cache")
st.markdown("A practical view of how semantic caching intercepts redundant queries to save LLM costs and reduce latency.")

# --- Top KPIs ---
stats = st.session_state.stats
hit_rate = (stats['cache_hits'] / stats['total_queries'] * 100) if stats['total_queries'] > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Queries", stats['total_queries'])
col2.metric("Cache Hit Rate", f"{hit_rate:.1f}%")
col3.metric("Time Saved", f"{stats['time_saved_s']:.1f}s")
col4.metric("Money Saved", f"${stats['money_saved']:.3f}")

st.divider()

# --- Query Interface ---
st.subheader("Ask a Question")
with st.form("query_form"):
    col_q, col_c, col_b = st.columns([3, 2, 1])
    with col_q:
        query = st.text_input("Question:", placeholder="e.g., What are Apple's risk factors?")
    with col_c:
        context = st.text_input("Context (Optional):", placeholder="e.g., Apple")
    with col_b:
        st.markdown("<br>", unsafe_allow_html=True) # align button
        submitted = st.form_submit_button("Submit", use_container_width=True)

if submitted and query:
    with st.spinner("Processing..."):
        try:
            # We hit /compare to easily get the 'what if' data for the UI stats
            res = requests.post(f"{API_URL}/compare", json={"query": query, "context": context}).json()
            
            t_no = res['fresh']['latency_s']
            t_yes = res['cached']['latency_s']
            source = res['cached']['response'].get('source', 'MISS')
            answer = res['cached']['response'].get('answer', '')
            
            # Update internal stats
            st.session_state.stats['total_queries'] += 1
            is_hit = source != "MISS"
            
            if is_hit:
                st.session_state.stats['cache_hits'] += 1
                st.session_state.stats['time_saved_s'] += (t_no - t_yes)
                st.session_state.stats['money_saved'] += 0.015  # Assumed cost per LLM call
            
            # Append to table history
            st.session_state.history.append({
                "Query": query,
                "Context": context,
                "Source": source,
                "Latency (Actual)": f"{t_yes:.3f}s",
                "Latency (If No Cache)": f"{t_no:.3f}s",
                "Status": "✅ HIT" if is_hit else "🐢 MISS",
                "Answer": answer
            })
            
            st.rerun()
        except Exception as e:
            st.error(f"API Error: {e}")

# --- Data Table View ---
st.subheader("Request Log & Audit Table")
if st.session_state.history:
    df = pd.DataFrame(st.session_state.history)
    
    # Display the table cleanly
    st.dataframe(
        df[["Query", "Context", "Status", "Source", "Latency (Actual)", "Latency (If No Cache)"]],
        use_container_width=True,
        hide_index=True
    )
    
    # Show the most recent answer below the table
    st.info(f"**Latest Answer:** {st.session_state.history[-1]['Answer']}")
    
    if st.button("Clear History & Cache"):
        requests.post(f"{API_URL}/clear_cache")
        st.session_state.history = []
        st.session_state.stats = {'total_queries': 0, 'cache_hits': 0, 'time_saved_s': 0.0, 'money_saved': 0.0}
        st.rerun()
else:
    st.markdown("*No queries run yet. Type a question above to start seeing data!*")

# --- Observability Links ---
st.divider()
st.markdown("**Internal Dashboards:** [View Qdrant Database](http://localhost:6333/dashboard) | [View Langfuse Traces](http://localhost:3001)")
