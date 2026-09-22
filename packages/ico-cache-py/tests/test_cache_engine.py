import asyncio
import hashlib

import pytest

from ico_cache.core.cache_engine import CacheEngine, _stable_id


async def test_resolve_l1_hit(engine):
    engine.set_l1("What is revenue?", {"answer": "42"}, tenant_id="tenant_a")
    res = await engine.resolve("What is revenue?", tenant_id="tenant_a")
    assert res == {"source": "L1", "response": {"answer": "42"}}


async def test_resolve_l1_is_tenant_scoped(engine):
    engine.set_l1("What is revenue?", {"answer": "42"}, tenant_id="tenant_a")
    res = await engine.resolve("What is revenue?", tenant_id="tenant_b")
    assert res["source"] != "L1"


async def test_resolve_l2_hit_roundtrips_structured_answer(engine):
    answer = {"answer": "semantic", "citations": ["a.htm"], "chunks": [{"source": "a.htm"}]}
    await engine.async_write_l2("How did sales trend?", answer, tenant_id="tenant_a")

    res = await engine.resolve("How did sales trend?", tenant_id="tenant_a")
    assert res["source"] == "L2"
    # LanceDB stores payloads as JSON text; the dict must survive the round-trip.
    assert res["response"] == answer


async def test_resolve_l3_hit(engine):
    await engine.async_write_l3("query text", "context text", {"answer": "l3"}, tenant_id="tenant_a")
    res = await engine.resolve("query text", context="context text", tenant_id="tenant_a")
    assert res["source"] == "L3"
    assert res["response"] == {"answer": "l3"}


async def test_resolve_miss(engine):
    res = await engine.resolve("never seen before", tenant_id="tenant_a")
    assert res == {"source": "MISS", "response": None}


async def test_single_flight_generates_once(engine):
    calls = 0

    async def generate():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"answer": "generated"}

    results = await asyncio.gather(
        *[
            engine.resolve_or_generate("same question", tenant_id="tenant_a", generate_fn=generate)
            for _ in range(20)
        ]
    )

    assert calls == 1, f"expected one generation, saw {calls}"
    assert all(r["response"] == {"answer": "generated"} for r in results)
    # And the shared result is cached for subsequent callers.
    assert (await engine.resolve("same question", tenant_id="tenant_a"))["source"] == "L1"


@pytest.mark.parametrize(
    "bad_answer",
    ["Insufficient context.", "", "   ", "LLM generation failed: 503 high demand"],
)
async def test_error_and_refusal_results_are_not_cached(engine, bad_answer):
    async def generate():
        return {"answer": bad_answer}

    res = await engine.resolve_or_generate("refusal query", tenant_id="tenant_a", generate_fn=generate)
    assert res["source"] == "MISS"
    assert (await engine.resolve("refusal query", tenant_id="tenant_a"))["source"] == "MISS"


async def test_generation_exception_propagates_and_is_not_cached(engine):
    async def boom():
        raise RuntimeError("llm down")

    with pytest.raises(RuntimeError):
        await engine.resolve_or_generate("exploding query", tenant_id="tenant_a", generate_fn=boom)

    assert (await engine.resolve("exploding query", tenant_id="tenant_a"))["source"] == "MISS"


async def test_backend_failure_degrades_to_miss(engine):
    async def boom(*args, **kwargs):
        raise RuntimeError("vector store unavailable")

    engine.get_l2 = boom
    engine.get_l3 = boom
    res = await engine.resolve("any query", context="ctx", tenant_id="tenant_a")
    assert res["source"] == "MISS"


async def test_slow_lookup_times_out_to_miss(engine):
    engine.lookup_timeout = 0.05

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.3)
        return {"answer": "late"}

    engine.get_l1 = slow
    res = await engine.resolve("slow query", tenant_id="tenant_a")
    assert res["source"] == "MISS"


def test_stable_id_is_process_independent_sha256():
    expected = int.from_bytes(hashlib.sha256("l2:tenant_a:q:".encode()).digest()[:8], "big") & ((1 << 63) - 1)
    assert _stable_id("l2", "tenant_a", "q", "") == expected
    assert _stable_id("a") == _stable_id("a")
    assert _stable_id("a") != _stable_id("b")


def test_l1_key_is_deterministic(engine):
    from ico_cache.backends.vector.lancedb_store import LanceDBStore
    from ico_cache.backends.exact.sqlite_store import SQLiteStore

    other = CacheEngine(
        embedder=engine.embedder,
        vector_store=LanceDBStore(uri=":memory:"),
        exact_store=SQLiteStore(db_path=":memory:"),
    )
    meta = {"entity": "MSFT", "quarter": "Q3"}
    assert engine._l1_key("Q", meta, tenant_id="t") == other._l1_key("Q", meta, tenant_id="t")
