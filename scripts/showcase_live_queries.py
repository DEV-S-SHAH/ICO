#!/usr/bin/env python3
"""Showcase script executing 50 challenging, multi-turn queries across L0a, L1, L2, and L3 cache tiers."""

import sys
import time
import json
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8000"

# (query, context, description)
QUERIES = [
    # -------------------------------------------------------------
    # Group 1: Deterministic Math & System Health (L0a HIT)
    # -------------------------------------------------------------
    ("calc: 1024 * 768", None, "High-res pixel math (L0a HIT)"),
    ("calc: (4500000 - 3200000) / 4500000", None, "Margin percentage calc (L0a HIT)"),
    ("ping", None, "System ping heartbeat (L0a HIT)"),
    ("calc: 13 ** 4", None, "Exponent calculation (L0a HIT)"),
    ("version", None, "Cache engine version check (L0a HIT)"),

    # -------------------------------------------------------------
    # Group 2: Difficult Multi-Turn Context Dialogues (L3 Showcase)
    # -------------------------------------------------------------
    # Dialogue A: Debt covenants and credit facilities
    (
        "What are the specific debt service coverage constraints and liquidity covenants stipulated in the credit facilities?",
        "Discussion with auditor reviewing Acmo Corp liquidity covenants and credit facility restrictions for FY2024.",
        "Dialogue A: Base turn (MISS -> populates L3)",
    ),
    (
        "Can you summarize the debt service constraints and liquidity covenant restrictions specified in credit agreements?",
        "Discussion with auditor reviewing Acmo Corp liquidity covenants and credit facility restrictions for FY2024.",
        "Dialogue A: Rephrased query in same context (L3 HIT)",
    ),
    (
        "What coverage ratios and covenant limits are imposed by the credit facilities?",
        "Follow-up regarding liquidity covenant restrictions and credit agreement debt service obligations.",
        "Dialogue A: Follow-up turn with evolved context (L3 HIT)",
    ),

    # Dialogue B: Amortized inference economics & caching bounds
    (
        "What are the formal amortized inference cost bounds and token economics across multi-tiered caching architectures?",
        "Technical architecture review on production LLM gateway throughput and latency tradeoffs.",
        "Dialogue B: Base turn (MISS -> populates L3)",
    ),
    (
        "Detail the amortized inference cost limits and economic bounds for multi-tiered caching systems.",
        "Technical architecture review on production LLM gateway throughput and latency tradeoffs.",
        "Dialogue B: Paraphrased query with matching context (L3 HIT)",
    ),
    (
        "Outline the asymptotic cost reduction and token efficiency bounds established by the tiered cache.",
        "Engineering evaluation of production LLM gateway latency tradeoffs and token cost economics.",
        "Dialogue B: Asymptotic cost follow-up (L3 HIT)",
    ),

    # Dialogue C: Tax rate reconciliation & statutory variance
    (
        "What factors explain the variance between the statutory tax rate and the effective consolidated tax rate in the filing?",
        "Accounting analysis examining GAAP vs non-GAAP income tax reconciliations and valuation allowances.",
        "Dialogue C: Base turn (MISS -> populates L3)",
    ),
    (
        "Explain the primary reconciliation items driving the difference between statutory and effective tax rates.",
        "Accounting analysis examining GAAP vs non-GAAP income tax reconciliations and valuation allowances.",
        "Dialogue C: Rephrased tax query in same context (L3 HIT)",
    ),

    # Dialogue D: Supplier concentration and procurement hazards
    (
        "What are the principal supplier concentration risks and single-source procurement vulnerabilities detailed by leadership?",
        "Risk management inquiry evaluating critical supply chain dependencies and component procurement resilience.",
        "Dialogue D: Base turn (MISS -> populates L3)",
    ),
    (
        "Identify the primary supplier concentration exposures and mitigation strategies outlined in disclosures.",
        "Risk management inquiry evaluating critical supply chain dependencies and component procurement resilience.",
        "Dialogue D: Rephrased supplier vulnerability query (L3 HIT)",
    ),

    # -------------------------------------------------------------
    # Group 3: Difficult Domain Queries (Establishing L1/L2)
    # -------------------------------------------------------------
    ("What was the consolidated operating margin trajectory between 2023 and 2024?", None, "Operating margin inquiry (L1/MISS)"),
    ("Enumerate the aggregate capital expenditure allocations and infrastructure investments deployed during the period.", None, "CapEx allocation inquiry (L1/MISS)"),
    ("What is the ratio of long-term debt to shareholders' equity reported on the balance sheet?", None, "Solvency ratio inquiry (L1/MISS)"),
    ("Summarize the enterprise vs commercial segment revenue distribution reported in audited statements.", None, "Segment revenue inquiry (L1/MISS)"),
    ("What dividend distributions were declared and approved by the board of directors?", None, "Dividend distribution inquiry (L1/MISS)"),
    ("What are the primary operational risks and macro headwinds highlighted in management discussion?", None, "Operational headwinds inquiry (L1/MISS)"),

    # -------------------------------------------------------------
    # Group 4: Exact Hits Across Complex Queries (L1 HIT)
    # -------------------------------------------------------------
    ("What was the consolidated operating margin trajectory between 2023 and 2024?", None, "Exact match: Margin trajectory (L1 HIT)"),
    ("Enumerate the aggregate capital expenditure allocations and infrastructure investments deployed during the period.", None, "Exact match: CapEx allocations (L1 HIT)"),
    ("What is the ratio of long-term debt to shareholders' equity reported on the balance sheet?", None, "Exact match: Solvency ratio (L1 HIT)"),
    ("Summarize the enterprise vs commercial segment revenue distribution reported in audited statements.", None, "Exact match: Segment breakdown (L1 HIT)"),
    ("What dividend distributions were declared and approved by the board of directors?", None, "Exact match: Dividend distributions (L1 HIT)"),
    ("What are the primary operational risks and macro headwinds highlighted in management discussion?", None, "Exact match: Operational headwinds (L1 HIT)"),

    # -------------------------------------------------------------
    # Group 5: Difficult Semantic Paraphrasing (L2 HIT)
    # -------------------------------------------------------------
    ("How did consolidated operating profitability and margins change from 2023 through 2024?", None, "Semantic paraphrase: Margins (L2 HIT)"),
    ("Detail the total capital outlays and facility investments made throughout the fiscal period.", None, "Semantic paraphrase: CapEx (L2 HIT)"),
    ("What is the debt to equity financial leverage ratio stated in the balance sheet?", None, "Semantic paraphrase: Leverage (L2 HIT)"),
    ("Provide the revenue contribution breakdown between commercial and enterprise operational segments.", None, "Semantic paraphrase: Segments (L2 HIT)"),
    ("Which shareholder dividend payouts were authorized by the governance board?", None, "Semantic paraphrase: Dividends (L2 HIT)"),
    ("What macroeconomic threats and operational vulnerabilities were documented in the MD&A section?", None, "Semantic paraphrase: Macro threats (L2 HIT)"),

    # -------------------------------------------------------------
    # Group 6: Additional Context-Aware Dialogue Hits (L3 HIT)
    # -------------------------------------------------------------
    (
        "Summarize the credit agreement covenants and debt service ratio compliance requirements.",
        "Discussion with auditor reviewing Acmo Corp liquidity covenants and credit facility restrictions for FY2024.",
        "Dialogue A: Covenant compliance check (L3 HIT)",
    ),
    (
        "What are the asymptotic bounds on amortized inference latency and token overhead?",
        "Technical architecture review on production LLM gateway throughput and latency tradeoffs.",
        "Dialogue B: Latency bound query (L3 HIT)",
    ),
    (
        "What tax adjustments bridge the GAAP statutory rate with the reported effective rate?",
        "Accounting analysis examining GAAP vs non-GAAP income tax reconciliations and valuation allowances.",
        "Dialogue C: Tax adjustment bridge (L3 HIT)",
    ),
    (
        "How is management addressing sole-source supplier vulnerabilities and critical component risks?",
        "Risk management inquiry evaluating critical supply chain dependencies and component procurement resilience.",
        "Dialogue D: Single-source mitigation (L3 HIT)",
    ),

    # -------------------------------------------------------------
    # Group 7: Functional Math and Fast Heartbeat (L0a HIT)
    # -------------------------------------------------------------
    ("calc: 999999 / 333", None, "Large division (L0a HIT)"),
    ("calc: 250 * 40 * 12", None, "Annualized headcount cost (L0a HIT)"),
    ("ping", None, "Liveness probe (L0a HIT)"),
    ("calc: 100 * (1.05 ** 10)", None, "10-year compound growth (L0a HIT)"),
    ("calc: round(3.14159265 * 25, 4)", None, "Geometric area calc (L0a HIT)"),

    # -------------------------------------------------------------
    # Group 8: Final Verification Queries Across Tiers (L1, L2, L3)
    # -------------------------------------------------------------
    (
        "Can you summarize the debt service constraints and liquidity covenant restrictions specified in credit agreements?",
        "Discussion with auditor reviewing Acmo Corp liquidity covenants and credit facility restrictions for FY2024.",
        "Dialogue A: Direct repetition (L1/L3 HIT)",
    ),
    ("What was the consolidated operating margin trajectory between 2023 and 2024?", None, "Rapid exact match (L1 HIT)"),
    ("How did consolidated operating profitability and margins change from 2023 through 2024?", None, "Rapid semantic match (L2 HIT)"),
    (
        "Detail the amortized inference cost limits and economic bounds for multi-tiered caching systems.",
        "Technical architecture review on production LLM gateway throughput and latency tradeoffs.",
        "Dialogue B: Amortized cost limits (L3 HIT)",
    ),
    ("calc: 50000 * 0.18", None, "Tax computation (L0a HIT)"),
    ("ping", None, "Final heartbeat (L0a HIT)"),
]

def send_query(query: str, context: str, desc: str, idx: int):
    url = f"{BASE_URL}/rag/query"
    body = {"query": query, "model": "gemini-1.5-flash"}
    if context:
        body["context"] = context

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = (time.time() - t0) * 1000
            cache_info = data.get("cache", {})
            cache_hit = cache_info.get("hit", False)
            layer = cache_info.get("layer", "MISS" if not cache_hit else "HIT")
            sim = cache_info.get("similarity")
            sim_str = f" (sim={sim:.3f})" if sim else ""
            saved = cache_info.get("tokens_saved", 0)

            # Color badge
            colors = {
                "L0a": "\033[96m",   # Cyan
                "L1": "\033[92m",    # Green
                "L2": "\033[94m",    # Blue
                "L3": "\033[95m",    # Magenta (L3 highlighted!)
            }
            c = colors.get(layer, "\033[92m")
            status_badge = f"{c}[{layer} HIT{sim_str}]\033[0m" if cache_hit else "\033[93m[MISS]\033[0m"

            ctx_flag = " [CTX]" if context else "      "
            print(f"[{idx:02d}/50] {status_badge:<28}{ctx_flag} {query[:45]:<45} | {elapsed:5.1f}ms | saved {saved:3d} toks | {desc}")
            return {
                "cache_hit": cache_hit,
                "cache_layer": layer,
                "tokens_saved": saved,
                "raw": data,
            }
    except Exception as e:
        print(f"[{idx:02d}/50] \033[91m[ERROR]\033[0m {query}: {e}")
        return None

def main():
    print("=" * 95)
    print("  SYNAPSE / ICO-CACHE: 50 CHALLENGING MULTI-TURN & CONTEXT-AWARE (L3) SHOWCASE")
    print("  Streaming live to Dashboard at http://localhost:3000")
    print("=" * 95)

    stats = {"hits": 0, "misses": 0, "L0a": 0, "L1": 0, "L2": 0, "L3": 0, "tokens_saved": 0}

    for i, (q, ctx, desc) in enumerate(QUERIES, 1):
        res = send_query(q, ctx, desc, i)
        if res:
            if res.get("cache_hit"):
                stats["hits"] += 1
                layer = res.get("cache_layer", "L1")
                stats[layer] = stats.get(layer, 0) + 1
                stats["tokens_saved"] += res.get("tokens_saved", 0)
            else:
                stats["misses"] += 1
        # Moderate interval so WebSocket updates stream visually into dashboard
        time.sleep(0.35)

    total = stats["hits"] + stats["misses"]
    hit_rate = (stats["hits"] / total * 100) if total else 0
    print("=" * 95)
    print(f" SHOWCASE SUMMARY:")
    print(f" Total Requests: {total}")
    print(f" Cache Hits:     {stats['hits']} ({hit_rate:.1f}%)")
    print(f"   - L0a (deterministic):          {stats.get('L0a', 0)}")
    print(f"   - L1  (exact match):            {stats.get('L1', 0)}")
    print(f"   - L2  (semantic sim):           {stats.get('L2', 0)}")
    print(f"   - L3  (context-aware dialogue): {stats.get('L3', 0)}  <-- L3 CONTEXT HITS")
    print(f" Cache Misses:   {stats['misses']}")
    print(f" Total Tokens Saved: {stats['tokens_saved']}")
    print("=" * 95)

if __name__ == "__main__":
    main()
